from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database import get_db
from backend import models
from backend import tmdb

router = APIRouter(prefix="/shows", tags=["shows"])


# --- Schemas ---

class ShowSearchRequest(BaseModel):
    query: str


class ShowAddRequest(BaseModel):
    tmdb_id: int
    status: str       # watching | watchlist | finished
    type: str = "tv"  # tv | movie


class ShowResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    poster_path: str | None
    status: str
    type: str
    added_at: str
    last_watched_at: str | None

    model_config = {"from_attributes": True}


# --- Endpoints ---

@router.post("/search")
async def search_shows(body: ShowSearchRequest):
    """Search TMDB by title. Returns results for the client to pick from."""
    results = await tmdb.search_tv(body.query)
    return [
        {
            "tmdb_id": r["id"],
            "title": r.get("name", ""),
            "overview": r.get("overview", ""),
            "first_air_date": r.get("first_air_date", ""),
            "poster_path": r.get("poster_path"),
        }
        for r in results
    ]


@router.post("/add", response_model=ShowResponse)
async def add_show(body: ShowAddRequest, db: Session = Depends(get_db)):
    """
    Add a show to the local DB. Idempotent — returns existing record if already tracked.
    Fetches canonical title and poster from TMDB.
    """
    if body.status not in ("watching", "watchlist", "finished"):
        raise HTTPException(status_code=422, detail="status must be watching, watchlist, or finished")

    existing = db.execute(
        select(models.Show).where(models.Show.tmdb_id == body.tmdb_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    try:
        details = await tmdb.get_show(body.tmdb_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch show details from TMDB")

    show = models.Show(
        tmdb_id=body.tmdb_id,
        title=details.get("name", "Unknown"),
        poster_path=details.get("poster_path"),
        status=body.status,
        type=body.type,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("", response_model=list[ShowResponse])
def list_shows(db: Session = Depends(get_db)):
    """List all tracked shows, ordered by most recently watched first."""
    shows = db.execute(
        select(models.Show).order_by(models.Show.last_watched_at.desc().nulls_last())
    ).scalars().all()
    return shows
