import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import and_, func, select, union
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend import models, tmdb

router = APIRouter(tags=["people"])


def _age_at(birthday: str | None, event_date: str | None) -> int | None:
    """Floor years between birthday and event_date (both YYYY-MM-DD strings)."""
    if not birthday or not event_date:
        return None
    try:
        b = date.fromisoformat(birthday)
        e = date.fromisoformat(event_date[:10])
        years = e.year - b.year
        if (e.month, e.day) < (b.month, b.day):
            years -= 1
        return years if years >= 0 else None
    except ValueError:
        return None


async def _ensure_cast_cached(show: models.Show, db: Session) -> None:
    """Fetch and cache show cast from TMDB if not yet cached."""
    count = db.execute(
        select(func.count()).select_from(models.ShowCast)
        .where(models.ShowCast.show_tmdb_id == show.tmdb_id)
    ).scalar()
    if count > 0:
        return

    data = await tmdb.get_show_credits(show.tmdb_id)
    for member in data.get("cast", []):
        person_id = member.get("id")
        if not person_id:
            continue

        # Upsert person
        person = db.execute(
            select(models.Person).where(models.Person.tmdb_id == person_id)
        ).scalar_one_or_none()
        if not person:
            db.add(models.Person(
                tmdb_id=person_id,
                name=member.get("name", "Unknown"),
                profile_path=member.get("profile_path"),
            ))

        # ShowCast entry (skip if already exists)
        exists = db.execute(
            select(models.ShowCast).where(
                models.ShowCast.show_tmdb_id == show.tmdb_id,
                models.ShowCast.person_tmdb_id == person_id,
            )
        ).scalar_one_or_none()
        if not exists:
            db.add(models.ShowCast(
                show_tmdb_id=show.tmdb_id,
                person_tmdb_id=person_id,
                character=member.get("character", ""),
                order=member.get("order", 999),
            ))

    db.commit()


async def _ensure_person_credits_cached(person: models.Person, db: Session) -> None:
    """Fetch and cache a person's full filmography from TMDB if not yet done."""
    if person.credits_cached_at:
        return

    data = await tmdb.get_person_credits(person.tmdb_id)
    for credit in data.get("cast", []):
        show_tmdb_id = credit.get("id")
        media_type = credit.get("media_type", "tv")
        if not show_tmdb_id or media_type not in ("tv", "movie"):
            continue

        title = credit.get("name") or credit.get("title") or "Unknown"

        first_air = credit.get("first_air_date") or credit.get("release_date") or None

        exists = db.execute(
            select(models.PersonCredit).where(
                models.PersonCredit.person_tmdb_id == person.tmdb_id,
                models.PersonCredit.show_tmdb_id == show_tmdb_id,
            )
        ).scalar_one_or_none()
        if not exists:
            db.add(models.PersonCredit(
                person_tmdb_id=person.tmdb_id,
                show_tmdb_id=show_tmdb_id,
                title=title,
                character=credit.get("character", ""),
                type=media_type,
                first_air_date=first_air,
            ))

    person.credits_cached_at = datetime.now(timezone.utc).isoformat()
    try:
        details = await tmdb.get_person(person.tmdb_id)
        person.birthday = details.get("birthday")
        person.imdb_id = details.get("imdb_id")
    except Exception:
        pass
    db.commit()


def _seen_in_counts(
    person_ids: list[int],
    db: Session,
    exclude_show_id: int | None = None,
) -> dict[int, int]:
    """
    Return {person_tmdb_id: count_of_watched_shows} for the given person IDs.
    Pass exclude_show_id to omit the current show from each person's count
    (so the badge reads "seen in X *other* things you've watched").
    """
    if not person_ids:
        return {}
    # TV: shows with at least one watched episode
    tv_watched = select(models.Episode.tmdb_show_id).distinct().where(
        models.Episode.watched == True  # noqa: E712
    )
    # Movies: shows with type=movie and watched=True
    movie_watched = select(models.Show.tmdb_id).where(
        models.Show.type == "movie",
        models.Show.watched == True,  # noqa: E712
    )
    watched_show_ids = union(tv_watched, movie_watched)
    q = (
        select(
            models.PersonCredit.person_tmdb_id,
            func.count(models.PersonCredit.show_tmdb_id.distinct()).label("cnt"),
        )
        .where(
            models.PersonCredit.person_tmdb_id.in_(person_ids),
            models.PersonCredit.show_tmdb_id.in_(watched_show_ids),
        )
    )
    if exclude_show_id is not None:
        q = q.where(models.PersonCredit.show_tmdb_id != exclude_show_id)
    rows = db.execute(q.group_by(models.PersonCredit.person_tmdb_id)).all()
    return {row.person_tmdb_id: row.cnt for row in rows}


async def _backfill_episode_credits(person_tmdb_id: int, show_tmdb_ids: list[int]) -> None:
    """
    Background task: for each show in show_tmdb_ids, fetch TMDB episode credits
    for every watched episode and populate EpisodeCredit rows for this person.
    Runs after the seen-in response is returned so the page load isn't blocked.
    """
    db = SessionLocal()
    try:
        for show_tmdb_id in show_tmdb_ids:
            watched_eps = db.execute(
                select(models.Episode.season_number, models.Episode.episode_number)
                .where(
                    models.Episode.tmdb_show_id == show_tmdb_id,
                    models.Episode.watched == True,  # noqa: E712
                )
                .order_by(models.Episode.season_number, models.Episode.episode_number)
            ).all()

            if not watched_eps:
                continue

            results = await asyncio.gather(
                *[tmdb.get_episode_credits(show_tmdb_id, row.season_number, row.episode_number)
                  for row in watched_eps],
                return_exceptions=True,
            )

            for row, result in zip(watched_eps, results):
                if isinstance(result, Exception):
                    continue
                all_members = result.get("cast", []) + result.get("guest_stars", [])
                for member in all_members:
                    if member.get("id") != person_tmdb_id:
                        continue
                    exists = db.execute(
                        select(models.EpisodeCredit).where(
                            models.EpisodeCredit.person_tmdb_id == person_tmdb_id,
                            models.EpisodeCredit.show_tmdb_id == show_tmdb_id,
                            models.EpisodeCredit.season_number == row.season_number,
                            models.EpisodeCredit.episode_number == row.episode_number,
                        )
                    ).scalar_one_or_none()
                    if not exists:
                        db.add(models.EpisodeCredit(
                            person_tmdb_id=person_tmdb_id,
                            show_tmdb_id=show_tmdb_id,
                            season_number=row.season_number,
                            episode_number=row.episode_number,
                            character=member.get("character", ""),
                        ))
            db.commit()
    finally:
        db.close()


@router.get("/shows/{tmdb_show_id}/cast")
async def get_show_cast(tmdb_show_id: int, db: Session = Depends(get_db)):
    """Get cast for a show, fetching from TMDB if not yet cached."""
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_show_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    await _ensure_cast_cached(show, db)

    rows = db.execute(
        select(models.ShowCast, models.Person)
        .join(models.Person, models.Person.tmdb_id == models.ShowCast.person_tmdb_id)
        .where(models.ShowCast.show_tmdb_id == tmdb_show_id)
        .order_by(models.ShowCast.order)
    ).all()

    person_ids = [sc.person_tmdb_id for sc, p in rows]
    seen_in_map = _seen_in_counts(person_ids, db, exclude_show_id=tmdb_show_id)

    return [
        {
            "person_tmdb_id": sc.person_tmdb_id,
            "name": p.name,
            "profile_path": p.profile_path,
            "character": sc.character,
            "order": sc.order,
            "seen_in_count": seen_in_map.get(sc.person_tmdb_id, 0),
        }
        for sc, p in rows
    ]


@router.get("/people/{tmdb_person_id}/all-credits")
def get_all_credits(tmdb_person_id: int, db: Session = Depends(get_db)):
    """Return all cached credits for a person (not filtered by watch history)."""
    person = db.execute(
        select(models.Person).where(models.Person.tmdb_id == tmdb_person_id)
    ).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    rows = db.execute(
        select(models.PersonCredit, models.Show.poster_path)
        .outerjoin(models.Show, models.Show.tmdb_id == models.PersonCredit.show_tmdb_id)
        .where(models.PersonCredit.person_tmdb_id == tmdb_person_id)
        .order_by(models.PersonCredit.first_air_date.desc().nulls_last())
    ).all()

    return [
        {
            "show_tmdb_id": pc.show_tmdb_id,
            "title": pc.title,
            "character": pc.character,
            "type": pc.type,
            "first_air_date": pc.first_air_date,
            "poster_path": poster_path,
        }
        for pc, poster_path in rows
    ]


@router.get("/people/{tmdb_person_id}/seen-in")
async def seen_in(tmdb_person_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Core WHIST query: return all credits for a person that overlap with
    the user's watch history (shows that have at least one watched episode).
    """
    person = db.execute(
        select(models.Person).where(models.Person.tmdb_id == tmdb_person_id)
    ).scalar_one_or_none()
    if not person:
        raise HTTPException(
            status_code=404,
            detail="Person not found — open a show's Cast panel first",
        )

    await _ensure_person_credits_cached(person, db)

    # Backfill birthday/imdb_id for actors cached before these features were added
    if person.birthday is None or person.imdb_id is None:
        try:
            details = await tmdb.get_person(person.tmdb_id)
            person.birthday = details.get("birthday")
            person.imdb_id = details.get("imdb_id")
            db.commit()
        except Exception:
            pass

    # Subquery: TV shows with at least one watched episode + watched movies
    tv_watched = select(models.Episode.tmdb_show_id).distinct().where(
        models.Episode.watched == True  # noqa: E712
    )
    movie_watched = select(models.Show.tmdb_id).where(
        models.Show.type == "movie",
        models.Show.watched == True,  # noqa: E712
    )
    watched_show_ids = union(tv_watched, movie_watched)

    # Main query: person's credits ∩ watch history, joined to shows for poster + air date fallback
    rows = db.execute(
        select(models.PersonCredit, models.Show.poster_path, models.Show.first_air_date)
        .outerjoin(models.Show, models.Show.tmdb_id == models.PersonCredit.show_tmdb_id)
        .where(
            models.PersonCredit.person_tmdb_id == tmdb_person_id,
            models.PersonCredit.show_tmdb_id.in_(watched_show_ids),
        )
        .order_by(models.PersonCredit.first_air_date.desc().nulls_last())
    ).all()

    # Determine main cast vs guest: person in ShowCast = main cast
    main_show_ids = set(db.execute(
        select(models.ShowCast.show_tmdb_id)
        .where(models.ShowCast.person_tmdb_id == tmdb_person_id)
    ).scalars().all())

    main_cast, guest = [], []
    for pc, poster_path, show_air_date in rows:
        air_date = pc.first_air_date or show_air_date
        entry = {
            "tmdb_id": pc.show_tmdb_id,
            "title": pc.title,
            "character": pc.character,
            "type": pc.type,
            "first_air_date": air_date,
            "age_at_filming": _age_at(person.birthday, air_date),
            "poster_path": poster_path,
        }
        if pc.show_tmdb_id in main_show_ids:
            main_cast.append(entry)
        elif pc.type == "movie":
            # Movies don't have episode-level credits
            entry["season_number"] = None
            entry["episode_number"] = None
            guest.append(entry)
        else:
            # Look up first watched episode for episode links
            ep = db.execute(
                select(models.EpisodeCredit)
                .join(models.Episode, and_(
                    models.Episode.tmdb_show_id == models.EpisodeCredit.show_tmdb_id,
                    models.Episode.season_number == models.EpisodeCredit.season_number,
                    models.Episode.episode_number == models.EpisodeCredit.episode_number,
                    models.Episode.watched == True,  # noqa: E712
                ))
                .where(
                    models.EpisodeCredit.person_tmdb_id == tmdb_person_id,
                    models.EpisodeCredit.show_tmdb_id == pc.show_tmdb_id,
                )
                .order_by(models.EpisodeCredit.season_number, models.EpisodeCredit.episode_number)
                .limit(1)
            ).scalar_one_or_none()
            entry["season_number"] = ep.season_number if ep else None
            entry["episode_number"] = ep.episode_number if ep else None
            guest.append(entry)

    # Trigger background backfill for TV guest shows that don't have episode links yet
    missing_ep_data = [
        entry["tmdb_id"] for entry in guest
        if entry["season_number"] is None and entry.get("type") != "movie"
    ]
    if missing_ep_data:
        background_tasks.add_task(_backfill_episode_credits, tmdb_person_id, missing_ep_data)

    return {
        "person": {
            "tmdb_id": person.tmdb_id,
            "name": person.name,
            "profile_path": person.profile_path,
            "birthday": person.birthday,
            "imdb_id": person.imdb_id,
        },
        "main_cast": main_cast,
        "guest": guest,
    }


@router.get("/shows/{tmdb_show_id}/season/{season_number}/episode/{episode_number}/cast")
async def get_episode_cast(
    tmdb_show_id: int,
    season_number: int,
    episode_number: int,
    db: Session = Depends(get_db),
):
    """
    Cast + guest stars for a specific episode, with seen-in counts.
    Persons are upserted and their credits pre-cached (parallel TMDB fetches)
    so badges are populated on first visit.
    """
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_show_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    try:
        data = await tmdb.get_episode_credits(tmdb_show_id, season_number, episode_number)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch episode credits from TMDB")

    cast = data.get("cast", [])
    guest_stars = data.get("guest_stars", [])
    all_members = cast + guest_stars

    # Upsert persons so they're available for person pages
    for member in all_members:
        person_id = member.get("id")
        if not person_id:
            continue
        exists = db.execute(
            select(models.Person).where(models.Person.tmdb_id == person_id)
        ).scalar_one_or_none()
        if not exists:
            db.add(models.Person(
                tmdb_id=person_id,
                name=member.get("name", "Unknown"),
                profile_path=member.get("profile_path"),
            ))
    db.commit()

    # Pre-cache credits for all persons whose credits aren't cached yet.
    # Fetch from TMDB in parallel, write to DB sequentially after.
    persons_to_cache = []
    for member in all_members:
        person_id = member.get("id")
        if not person_id:
            continue
        person = db.execute(
            select(models.Person).where(models.Person.tmdb_id == person_id)
        ).scalar_one_or_none()
        if person and not person.credits_cached_at:
            persons_to_cache.append(person)

    if persons_to_cache:
        credit_results = await asyncio.gather(
            *[tmdb.get_person_credits(p.tmdb_id) for p in persons_to_cache],
            return_exceptions=True,
        )
        for person, result in zip(persons_to_cache, credit_results):
            if isinstance(result, Exception):
                continue
            for credit in result.get("cast", []):
                show_id = credit.get("id")
                media_type = credit.get("media_type", "tv")
                if not show_id or media_type not in ("tv", "movie"):
                    continue
                title = credit.get("name") or credit.get("title") or "Unknown"
                already = db.execute(
                    select(models.PersonCredit).where(
                        models.PersonCredit.person_tmdb_id == person.tmdb_id,
                        models.PersonCredit.show_tmdb_id == show_id,
                    )
                ).scalar_one_or_none()
                if not already:
                    db.add(models.PersonCredit(
                        person_tmdb_id=person.tmdb_id,
                        show_tmdb_id=show_id,
                        title=title,
                        character=credit.get("character", ""),
                        type=media_type,
                    ))
            person.credits_cached_at = datetime.now(timezone.utc).isoformat()
        db.commit()

    # Populate EpisodeCredit rows for all cast members (main cast + guest stars)
    for member in all_members:
        person_id = member.get("id")
        if not person_id:
            continue
        exists = db.execute(
            select(models.EpisodeCredit).where(
                models.EpisodeCredit.person_tmdb_id == person_id,
                models.EpisodeCredit.show_tmdb_id == tmdb_show_id,
                models.EpisodeCredit.season_number == season_number,
                models.EpisodeCredit.episode_number == episode_number,
            )
        ).scalar_one_or_none()
        if not exists:
            db.add(models.EpisodeCredit(
                person_tmdb_id=person_id,
                show_tmdb_id=tmdb_show_id,
                season_number=season_number,
                episode_number=episode_number,
                character=member.get("character", ""),
            ))
    db.commit()

    # Seen-in counts, excluding the current show so "1 = only this show" → hidden
    all_ids = [m.get("id") for m in all_members if m.get("id")]
    seen_in_map = _seen_in_counts(all_ids, db, exclude_show_id=tmdb_show_id)

    def fmt(m):
        return {
            "person_tmdb_id": m.get("id"),
            "name": m.get("name", ""),
            "profile_path": m.get("profile_path"),
            "character": m.get("character", ""),
            "order": m.get("order", 999),
            "seen_in_count": seen_in_map.get(m.get("id"), 0),
        }

    return {
        "cast": sorted([fmt(m) for m in cast if m.get("id")], key=lambda x: x["order"]),
        "guest_stars": sorted([fmt(m) for m in guest_stars if m.get("id")], key=lambda x: x["order"]),
    }
