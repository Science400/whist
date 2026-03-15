from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models, tmdb

router = APIRouter(prefix="/movies", tags=["movies"])


async def _ensure_movie_cast_cached(movie: models.Show, db: Session) -> None:
    """Fetch and cache movie cast from TMDB if not yet cached."""
    from sqlalchemy import func
    count = db.execute(
        select(func.count()).select_from(models.ShowCast)
        .where(models.ShowCast.show_tmdb_id == movie.tmdb_id)
    ).scalar()
    if count > 0:
        return

    data = await tmdb.get_movie_credits(movie.tmdb_id)
    for member in data.get("cast", []):
        person_id = member.get("id")
        if not person_id:
            continue

        person = db.execute(
            select(models.Person).where(models.Person.tmdb_id == person_id)
        ).scalar_one_or_none()
        if not person:
            db.add(models.Person(
                tmdb_id=person_id,
                name=member.get("name", "Unknown"),
                profile_path=member.get("profile_path"),
            ))

        exists = db.execute(
            select(models.ShowCast).where(
                models.ShowCast.show_tmdb_id == movie.tmdb_id,
                models.ShowCast.person_tmdb_id == person_id,
            )
        ).scalar_one_or_none()
        if not exists:
            db.add(models.ShowCast(
                show_tmdb_id=movie.tmdb_id,
                person_tmdb_id=person_id,
                character=member.get("character", ""),
                order=member.get("order", 999),
            ))

    db.commit()


class MovieAddRequest(BaseModel):
    tmdb_id: int
    user_status: str = "watchlist"  # watchlist | finished | abandoned


class MovieStatusRequest(BaseModel):
    user_status: str


_VALID_STATUSES = {"watchlist", "finished", "abandoned"}


@router.get("/search")
async def search_movies(q: str):
    """Search TMDB for movies."""
    results = await tmdb.search_movie(q)
    return [
        {
            "tmdb_id": r["id"],
            "title": r.get("title", ""),
            "overview": r.get("overview", ""),
            "release_date": r.get("release_date", ""),
            "poster_path": r.get("poster_path"),
        }
        for r in results
    ]


@router.post("")
async def add_movie(body: MovieAddRequest, db: Session = Depends(get_db)):
    """Add a movie to the library. Idempotent."""
    if body.user_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"user_status must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    existing = db.execute(
        select(models.Show).where(models.Show.tmdb_id == body.tmdb_id)
    ).scalar_one_or_none()
    if existing:
        return _fmt_movie(existing)

    try:
        details = await tmdb.get_movie(body.tmdb_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch movie details from TMDB")

    movie = models.Show(
        tmdb_id=body.tmdb_id,
        title=details.get("title", "Unknown"),
        poster_path=details.get("poster_path"),
        user_status=body.user_status,
        type="movie",
        added_at=datetime.now(timezone.utc).isoformat(),
        first_air_date=details.get("release_date"),
        watched=False,
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return _fmt_movie(movie)


@router.get("")
def list_movies(db: Session = Depends(get_db)):
    """List all movies in the library."""
    movies = db.execute(
        select(models.Show)
        .where(models.Show.type == "movie")
        .order_by(models.Show.last_watched_at.desc().nulls_last(), models.Show.added_at.desc())
    ).scalars().all()
    return [_fmt_movie(m) for m in movies]


@router.get("/{tmdb_id}")
async def get_movie_detail(tmdb_id: int, db: Session = Depends(get_db)):
    """Movie detail: TMDB metadata + local tracking state + cast."""
    movie = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id, models.Show.type == "movie")
    ).scalar_one_or_none()

    try:
        details = await tmdb.get_movie(tmdb_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch movie details from TMDB")

    return {
        "tmdb_id": tmdb_id,
        "tracked": movie is not None,
        "user_status": movie.user_status if movie else None,
        "watched": movie.watched if movie else False,
        "watched_at": movie.watched_at if movie else None,
        "title": details.get("title"),
        "poster_path": details.get("poster_path"),
        "backdrop_path": details.get("backdrop_path"),
        "overview": details.get("overview"),
        "release_date": details.get("release_date", "")[:4],
        "runtime": details.get("runtime"),
        "imdb_id": details.get("imdb_id"),
        "genres": [g["name"] for g in details.get("genres", [])],
    }


@router.post("/{tmdb_id}/watched")
def toggle_watched(tmdb_id: int, db: Session = Depends(get_db)):
    """Toggle watched state for a movie."""
    movie = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id, models.Show.type == "movie")
    ).scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not tracked")

    movie.watched = not movie.watched
    if movie.watched:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        movie.watched_at = now
        movie.last_watched_at = now
        if movie.user_status == "watchlist":
            movie.user_status = "finished"
    else:
        movie.watched_at = None

    db.commit()
    return {"tmdb_id": tmdb_id, "watched": movie.watched, "watched_at": movie.watched_at}


@router.patch("/{tmdb_id}/status")
def update_movie_status(tmdb_id: int, body: MovieStatusRequest, db: Session = Depends(get_db)):
    """Update user_status for a movie."""
    user_status = body.user_status
    if user_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"user_status must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    movie = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id, models.Show.type == "movie")
    ).scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not tracked")
    movie.user_status = user_status
    db.commit()
    return {"tmdb_id": tmdb_id, "user_status": movie.user_status}


@router.get("/{tmdb_id}/cast")
async def get_movie_cast(tmdb_id: int, db: Session = Depends(get_db)):
    """Get cast for a movie, fetching from TMDB if not yet cached."""
    from backend.routers.people import _seen_in_counts

    movie = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id, models.Show.type == "movie")
    ).scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not tracked")

    await _ensure_movie_cast_cached(movie, db)

    rows = db.execute(
        select(models.ShowCast, models.Person)
        .join(models.Person, models.Person.tmdb_id == models.ShowCast.person_tmdb_id)
        .where(models.ShowCast.show_tmdb_id == tmdb_id)
        .order_by(models.ShowCast.order)
    ).all()

    person_ids = [sc.person_tmdb_id for sc, p in rows]
    seen_in_map = _seen_in_counts(person_ids, db, exclude_show_id=tmdb_id)

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


def _fmt_movie(m: models.Show) -> dict:
    return {
        "id": m.id,
        "tmdb_id": m.tmdb_id,
        "title": m.title,
        "poster_path": m.poster_path,
        "user_status": m.user_status,
        "type": m.type,
        "added_at": m.added_at,
        "watched": bool(m.watched),
        "watched_at": m.watched_at,
        "first_air_date": m.first_air_date,
        "last_watched_at": m.last_watched_at,
    }
