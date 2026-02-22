from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models, tmdb

# No prefix — this router defines full paths (/shows/{id}/episodes and /episodes/watched)
router = APIRouter(tags=["episodes"])


async def _ensure_episodes_cached(show: models.Show, db: Session) -> None:
    """Fetch and cache all non-special seasons from TMDB if not yet cached."""
    count = db.execute(
        select(func.count()).select_from(models.Episode)
        .where(models.Episode.tmdb_show_id == show.tmdb_id)
    ).scalar()
    if count > 0:
        return

    details = await tmdb.get_show(show.tmdb_id)
    for season in details.get("seasons", []):
        season_num = season["season_number"]
        if season_num == 0:  # skip specials
            continue
        try:
            season_data = await tmdb.get_season(show.tmdb_id, season_num)
        except Exception:
            continue
        for ep in season_data.get("episodes", []):
            ep_num = ep.get("episode_number")
            if ep_num is None:
                continue
            exists = db.execute(
                select(models.Episode).where(
                    models.Episode.tmdb_show_id == show.tmdb_id,
                    models.Episode.season_number == season_num,
                    models.Episode.episode_number == ep_num,
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(models.Episode(
                    show_id=show.id,
                    tmdb_show_id=show.tmdb_id,
                    season_number=season_num,
                    episode_number=ep_num,
                    title=ep.get("name"),
                    air_date=ep.get("air_date"),
                    watched=False,
                ))
    db.commit()


@router.get("/shows/{tmdb_show_id}/episodes")
async def get_show_episodes(tmdb_show_id: int, db: Session = Depends(get_db)):
    """Get all episodes for a show, fetching from TMDB if not yet cached."""
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_show_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    await _ensure_episodes_cached(show, db)

    episodes = db.execute(
        select(models.Episode)
        .where(models.Episode.tmdb_show_id == tmdb_show_id)
        .order_by(models.Episode.season_number, models.Episode.episode_number)
    ).scalars().all()

    return [
        {
            "id": ep.id,
            "season_number": ep.season_number,
            "episode_number": ep.episode_number,
            "title": ep.title,
            "air_date": ep.air_date,
            "watched": ep.watched,
            "watched_at": ep.watched_at,
        }
        for ep in episodes
    ]


@router.get("/shows/{tmdb_show_id}/season/{season_number}")
async def get_season_detail(
    tmdb_show_id: int, season_number: int, db: Session = Depends(get_db)
):
    """
    Season detail: TMDB metadata + episode list with local watch state.
    Requires the show to be tracked.
    """
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_show_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    await _ensure_episodes_cached(show, db)

    try:
        season_data = await tmdb.get_season(tmdb_show_id, season_number)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch season from TMDB")

    # Merge TMDB episode metadata with local watch state
    episodes_db = {
        ep.episode_number: ep
        for ep in db.execute(
            select(models.Episode).where(
                models.Episode.tmdb_show_id == tmdb_show_id,
                models.Episode.season_number == season_number,
            )
        ).scalars().all()
    }

    episodes = []
    for ep in season_data.get("episodes", []):
        ep_num = ep.get("episode_number")
        local = episodes_db.get(ep_num)
        episodes.append({
            "episode_number": ep_num,
            "title": ep.get("name"),
            "air_date": ep.get("air_date"),
            "overview": ep.get("overview"),
            "still_path": ep.get("still_path"),
            "watched": local.watched if local else False,
            "watched_at": local.watched_at if local else None,
        })

    return {
        "tmdb_show_id": tmdb_show_id,
        "season_number": season_number,
        "name": season_data.get("name"),
        "poster_path": season_data.get("poster_path"),
        "overview": season_data.get("overview"),
        "air_date": (season_data.get("air_date") or "")[:4],
        "episodes": episodes,
    }


@router.get("/shows/{tmdb_show_id}/progress")
async def get_show_progress(tmdb_show_id: int, db: Session = Depends(get_db)):
    """Get watch progress summary for a show."""
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_show_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    total = db.execute(
        select(func.count()).select_from(models.Episode)
        .where(models.Episode.tmdb_show_id == tmdb_show_id)
    ).scalar()

    watched = db.execute(
        select(func.count()).select_from(models.Episode)
        .where(
            models.Episode.tmdb_show_id == tmdb_show_id,
            models.Episode.watched == True,  # noqa: E712
        )
    ).scalar()

    next_ep = db.execute(
        select(models.Episode)
        .where(
            models.Episode.tmdb_show_id == tmdb_show_id,
            models.Episode.watched == False,  # noqa: E712
        )
        .order_by(models.Episode.season_number, models.Episode.episode_number)
    ).scalar_one_or_none()

    return {
        "tmdb_show_id": tmdb_show_id,
        "total": total,
        "watched": watched,
        "percent": round(watched / total * 100, 1) if total > 0 else 0.0,
        "next_unwatched": {
            "season_number": next_ep.season_number,
            "episode_number": next_ep.episode_number,
            "title": next_ep.title,
        } if next_ep else None,
    }


# --- Schemas ---

def _today() -> str:
    return date.today().isoformat()


class WatchedRequest(BaseModel):
    tmdb_show_id: int
    season_number: int
    episode_number: int
    watched: bool = True            # False to unwatch
    watched_at: str | None = "today"  # "today" | YYYY-MM-DD | null (no date)


class BulkWatchedRequest(BaseModel):
    tmdb_show_id: int
    season_number: int | None = None  # None = entire show
    watched_at: str | None = "today"  # "today" | YYYY-MM-DD | null (no date)


def _resolve_date(watched_at: str | None) -> str | None:
    """Resolve the watched_at field to a YYYY-MM-DD string or None."""
    if watched_at == "today":
        return date.today().isoformat()
    return watched_at  # either a YYYY-MM-DD string or None


# --- Endpoints ---

@router.post("/episodes/watched")
def mark_episode_watched(body: WatchedRequest, db: Session = Depends(get_db)):
    """Mark a single episode watched or unwatched."""
    ep = db.execute(
        select(models.Episode).where(
            models.Episode.tmdb_show_id == body.tmdb_show_id,
            models.Episode.season_number == body.season_number,
            models.Episode.episode_number == body.episode_number,
        )
    ).scalar_one_or_none()
    if not ep:
        raise HTTPException(
            status_code=404,
            detail="Episode not found — open the Episodes panel first to cache them",
        )

    ep.watched = body.watched
    ep.watched_at = _resolve_date(body.watched_at) if body.watched else None

    if body.watched:
        show = db.get(models.Show, ep.show_id)
        if show:
            show.last_watched_at = datetime.now(timezone.utc).isoformat()

    db.commit()
    return {"watched": ep.watched, "watched_at": ep.watched_at}


@router.post("/episodes/watched/bulk")
def mark_bulk_watched(body: BulkWatchedRequest, db: Session = Depends(get_db)):
    """Mark an entire season (or whole show) as watched."""
    query = select(models.Episode).where(
        models.Episode.tmdb_show_id == body.tmdb_show_id,
        models.Episode.watched == False,  # noqa: E712
    )
    if body.season_number is not None:
        query = query.where(models.Episode.season_number == body.season_number)

    episodes = db.execute(query).scalars().all()
    if not episodes:
        return {"marked": 0}

    resolved_date = _resolve_date(body.watched_at)
    for ep in episodes:
        ep.watched = True
        ep.watched_at = resolved_date

    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == body.tmdb_show_id)
    ).scalar_one_or_none()
    if show:
        show.last_watched_at = datetime.now(timezone.utc).isoformat()

    db.commit()
    return {"marked": len(episodes)}
