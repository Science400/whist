from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _ep_card(show: models.Show, ep: models.Episode, available_count: int, suggested_count: int) -> dict:
    return {
        "show": {
            "tmdb_id": show.tmdb_id,
            "title": show.title,
            "poster_path": show.poster_path,
            "user_status": show.user_status,
            "watch_pace": show.watch_pace or "binge",
        },
        "next_episode": {
            "season_number": ep.season_number,
            "episode_number": ep.episode_number,
            "title": ep.title,
            "air_date": ep.air_date,
        },
        "available_count": available_count,   # >1 shows "N available" badge for airing shows
        "suggested_count": suggested_count,   # 2 for fast pace, 0 otherwise
    }


@router.get("/today")
def get_schedule_today(db: Session = Depends(get_db)):
    """
    Return a single ordered list of shows to watch today.

    Airing shows (with unwatched aired episodes) come first, then watching shows
    (filtered by pace setting). Within each group, sorted by least-recently-watched first.
    """
    tod           = date.today().isoformat()
    cutoff_weekly = (date.today() - timedelta(days=7)).isoformat()

    airing_shows = db.execute(
        select(models.Show)
        .where(models.Show.user_status == "airing")
        .order_by(models.Show.last_watched_at.asc().nulls_last())
    ).scalars().all()

    watching_shows = db.execute(
        select(models.Show)
        .where(models.Show.user_status == "watching")
        .order_by(models.Show.last_watched_at.asc().nulls_last())
    ).scalars().all()

    items = []

    # --- Airing shows: include if any unwatched aired episode exists ---
    for show in airing_shows:
        available_count = db.execute(
            select(func.count()).select_from(models.Episode)
            .where(
                models.Episode.tmdb_show_id == show.tmdb_id,
                models.Episode.watched == False,  # noqa: E712
                models.Episode.air_date.isnot(None),
                models.Episode.air_date <= tod,
            )
        ).scalar() or 0

        if available_count == 0:
            continue

        next_ep = db.execute(
            select(models.Episode)
            .where(
                models.Episode.tmdb_show_id == show.tmdb_id,
                models.Episode.watched == False,  # noqa: E712
                models.Episode.air_date.isnot(None),
                models.Episode.air_date <= tod,
            )
            .order_by(models.Episode.season_number, models.Episode.episode_number)
            .limit(1)
        ).scalar_one_or_none()

        if next_ep:
            items.append(_ep_card(show, next_ep, available_count, 0))

    # --- Watching shows: filtered by pace setting ---
    for show in watching_shows:
        pace = show.watch_pace or "binge"
        lwa  = show.last_watched_at

        # Weekly pace: skip if watched within the last 7 days
        if pace == "weekly" and lwa and lwa >= cutoff_weekly:
            continue

        next_ep = db.execute(
            select(models.Episode)
            .where(
                models.Episode.tmdb_show_id == show.tmdb_id,
                models.Episode.watched == False,  # noqa: E712
            )
            .order_by(models.Episode.season_number, models.Episode.episode_number)
            .limit(1)
        ).scalar_one_or_none()

        if next_ep:
            suggested = 2 if pace == "fast" else 0
            items.append(_ep_card(show, next_ep, 0, suggested))

    return {"items": items}
