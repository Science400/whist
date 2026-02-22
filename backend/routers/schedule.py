from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _ep_card(show: models.Show, ep: models.Episode, new_count: int) -> dict:
    return {
        "show": {
            "tmdb_id": show.tmdb_id,
            "title": show.title,
            "poster_path": show.poster_path,
            "user_status": show.user_status,
        },
        "next_episode": {
            "season_number": ep.season_number,
            "episode_number": ep.episode_number,
            "title": ep.title,
            "air_date": ep.air_date,
        },
        "new_count": new_count,
    }


@router.get("/today")
def get_schedule_today(db: Session = Depends(get_db)):
    """
    Return four schedule sections based on user_status and watch activity.
    Sections are mutually exclusive (priority order: airing_now → keep_watching
    → up_next → pick_up_again).
    """
    tod = date.today().isoformat()
    cutoff_new    = (date.today() - timedelta(days=7)).isoformat()   # "new" airing window
    cutoff_active = (date.today() - timedelta(days=14)).isoformat()  # "keep watching" threshold
    cutoff_idle   = (date.today() - timedelta(days=30)).isoformat()  # "pick up again" threshold

    # All tracked shows ordered by least recently watched first
    all_shows = db.execute(
        select(models.Show).order_by(models.Show.last_watched_at.asc().nulls_last())
    ).scalars().all()

    airing_now    = []
    keep_watching = []
    up_next       = []
    pick_up_again = []

    for show in all_shows:
        status = show.user_status or ""
        lwa    = show.last_watched_at  # ISO string or None

        # --- Airing Now: airing shows with new unwatched eps in last 7 days ---
        if status == "airing":
            new_count = db.execute(
                select(func.count()).select_from(models.Episode)
                .where(
                    models.Episode.tmdb_show_id == show.tmdb_id,
                    models.Episode.watched == False,  # noqa: E712
                    models.Episode.air_date.isnot(None),
                    models.Episode.air_date >= cutoff_new,
                    models.Episode.air_date <= tod,
                )
            ).scalar()

            if new_count > 0:
                next_ep = db.execute(
                    select(models.Episode)
                    .where(
                        models.Episode.tmdb_show_id == show.tmdb_id,
                        models.Episode.watched == False,  # noqa: E712
                        models.Episode.air_date.isnot(None),
                        models.Episode.air_date >= cutoff_new,
                        models.Episode.air_date <= tod,
                    )
                    .order_by(models.Episode.season_number, models.Episode.episode_number)
                    .limit(1)
                ).scalar_one_or_none()
                if next_ep:
                    airing_now.append(_ep_card(show, next_ep, new_count))
                    continue

        # --- Keep Watching: binging + recently active ---
        if status == "binging" and lwa and lwa >= cutoff_active:
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
                keep_watching.append(_ep_card(show, next_ep, 0))
                continue

        # --- Up Next: binging + idle ---
        if status == "binging":
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
                up_next.append(_ep_card(show, next_ep, 0))
                continue

        # --- Pick Up Again: airing/binging, idle 30+ days, has unwatched aired eps ---
        if status in ("airing", "binging") and lwa and lwa < cutoff_idle:
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
                pick_up_again.append(_ep_card(show, next_ep, 0))

    return {
        "airing_now":    airing_now,
        "keep_watching": keep_watching,
        "up_next":       up_next,
        "pick_up_again": pick_up_again,
    }
