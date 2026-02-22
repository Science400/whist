import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models, tmdb

router = APIRouter(tags=["people"])


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
            ))

    person.credits_cached_at = datetime.now(timezone.utc).isoformat()
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
    watched_show_ids = (
        select(models.Episode.tmdb_show_id).distinct()
        .where(models.Episode.watched == True)  # noqa: E712
    )
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
        .order_by(models.PersonCredit.title)
    ).all()

    return [
        {
            "show_tmdb_id": pc.show_tmdb_id,
            "title": pc.title,
            "character": pc.character,
            "type": pc.type,
            "poster_path": poster_path,
        }
        for pc, poster_path in rows
    ]


@router.get("/people/{tmdb_person_id}/seen-in")
async def seen_in(tmdb_person_id: int, db: Session = Depends(get_db)):
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

    # Subquery: tmdb_show_ids with at least one watched episode
    watched_show_ids = (
        select(models.Episode.tmdb_show_id).distinct()
        .where(models.Episode.watched == True)  # noqa: E712
    )

    # Main query: person's credits ∩ watch history, joined to shows for poster
    rows = db.execute(
        select(models.PersonCredit, models.Show.poster_path)
        .outerjoin(models.Show, models.Show.tmdb_id == models.PersonCredit.show_tmdb_id)
        .where(
            models.PersonCredit.person_tmdb_id == tmdb_person_id,
            models.PersonCredit.show_tmdb_id.in_(watched_show_ids),
        )
        .order_by(models.PersonCredit.title)
    ).all()

    return {
        "person": {
            "tmdb_id": person.tmdb_id,
            "name": person.name,
            "profile_path": person.profile_path,
        },
        "seen_in": [
            {
                "tmdb_id": pc.show_tmdb_id,
                "title": pc.title,
                "character": pc.character,
                "type": pc.type,
                "poster_path": poster_path,
            }
            for pc, poster_path in rows
        ],
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
