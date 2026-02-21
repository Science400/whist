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

    return [
        {
            "person_tmdb_id": sc.person_tmdb_id,
            "name": p.name,
            "profile_path": p.profile_path,
            "character": sc.character,
            "order": sc.order,
        }
        for sc, p in rows
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
