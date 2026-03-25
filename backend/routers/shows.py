from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func, case

from backend.database import get_db
from backend import models
from backend import tmdb

router = APIRouter(prefix="/shows", tags=["shows"])

_VALID_STATUSES = {"airing", "watching", "finished", "watchlist", "abandoned", "hiatus"}
_VALID_PACES    = {"binge", "fast", "weekly"}


class WikiRequest(BaseModel):
    label: str
    url: str
    season_url_template: str | None = None


def _norm_name(name: str) -> str:
    """Normalize brand symbols so 'Paramount+' and 'Paramount Plus' compare equal."""
    return (
        name.replace("Paramount+", "Paramount Plus")
            .replace("Disney+", "Disney Plus")
            .replace("Apple TV+", "Apple TV Plus")
            .strip()
            .lower()
    )


_BRAND_DISPLAY = {
    "paramount plus": "Paramount+",
    "disney plus":    "Disney+",
    "apple tv plus":  "Apple TV+",
    "apple tv":       "Apple TV",
    "amazon prime":   "Prime Video",
    "hbo max":        "Max",
}


def _lcp_words(word_lists: list[list[str]]) -> list[str]:
    """Longest common word-prefix across all lists."""
    prefix = list(word_lists[0])
    for wl in word_lists[1:]:
        prefix = [a for a, b in zip(prefix, wl) if a == b]
        if not prefix:
            break
    return prefix


def _dedup_providers(providers: list) -> list:
    """Keep one provider per brand.

    Groups by first word of normalized name.  Within each group the entry with
    the shortest normalized name is used for the logo (fewest add-on qualifiers),
    and the display name is replaced with the longest common word-prefix of the
    group (e.g. all Paramount+ variants → 'Paramount+').
    """
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for p in providers:
        words = _norm_name(p["provider_name"]).split()
        key = words[0] if words else "__empty__"
        groups[key].append(p)

    result = []
    for members in groups.values():
        word_lists = [_norm_name(p["provider_name"]).split() for p in members]

        # Shortest-name entry → cleanest logo (fewest add-on words)
        best = min(members, key=lambda p: (len(_norm_name(p["provider_name"])), p["provider_id"]))

        # Override display name with LCP, mapped to known brand names
        lcp_str = " ".join(_lcp_words(word_lists))
        display = _BRAND_DISPLAY.get(lcp_str, lcp_str.title())
        result.append({**best, "provider_name": display})

    result.sort(key=lambda p: p["provider_id"])
    return result

# TMDB statuses that mean the show is still airing (used when auto-suggesting status on add)
_ACTIVE_TMDB_STATUSES = {"Returning Series", "In Production", "Planned", "Pilot"}


# --- Schemas ---

class ShowSearchRequest(BaseModel):
    query: str


class ShowAddRequest(BaseModel):
    tmdb_id: int
    user_status: str = "airing"   # airing | watching | finished | watchlist | abandoned
    type: str = "tv"


class ShowStatusRequest(BaseModel):
    user_status: str


class ShowPaceRequest(BaseModel):
    watch_pace: str


class ShowResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    poster_path: str | None
    user_status: str | None
    type: str
    added_at: str
    last_watched_at: str | None
    watched_count: int = 0
    total_count: int = 0
    first_air_date: str | None = None

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


@router.get("/{tmdb_id}/detail")
async def get_show_detail(tmdb_id: int, db: Session = Depends(get_db)):
    """
    Combined show detail: TMDB metadata + local tracking state.
    Works for both tracked and untracked shows.
    """
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id)
    ).scalar_one_or_none()

    wikis = db.execute(
        select(models.ShowWiki).where(models.ShowWiki.show_tmdb_id == tmdb_id)
        .order_by(models.ShowWiki.id)
    ).scalars().all()

    try:
        details = await tmdb.get_show(tmdb_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch show details from TMDB")

    return {
        "tmdb_id": tmdb_id,
        "tracked": show is not None,
        "user_status": show.user_status if show else None,
        "watch_pace": (show.watch_pace or "binge") if show else None,
        "title": details.get("name"),
        "poster_path": details.get("poster_path"),
        "backdrop_path": details.get("backdrop_path"),
        "overview": details.get("overview"),
        "first_air_date": details.get("first_air_date", "")[:4],  # year only
        "last_air_date": details.get("last_air_date", "")[:4],
        "tmdb_status": details.get("status"),   # "Returning Series", "Ended", etc.
        "imdb_id": details.get("external_ids", {}).get("imdb_id"),
        "wikis": [{"id": w.id, "label": w.label, "url": w.url, "season_url_template": w.season_url_template} for w in wikis],
        "networks": [n.get("name") for n in details.get("networks", [])],
        "seasons": [
            {
                "season_number": s["season_number"],
                "episode_count": s.get("episode_count", 0),
                "name": s.get("name"),
                "poster_path": s.get("poster_path"),
                "air_date": (s.get("air_date") or "")[:4],
            }
            for s in details.get("seasons", [])
            if s["season_number"] > 0
        ],
    }


@router.get("/{tmdb_id}/watch-providers")
async def get_show_watch_providers(tmdb_id: int):
    """Streaming and rental providers for a show (US region, from TMDB)."""
    try:
        data = await tmdb.get_watch_providers(tmdb_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch watch providers from TMDB")

    us = data.get("results", {}).get("US", {})

    def fmt(p):
        return {
            "provider_id":   p["provider_id"],
            "provider_name": p["provider_name"],
            "logo_path":     p.get("logo_path"),
        }

    return {
        "streaming": _dedup_providers([fmt(p) for p in us.get("flatrate", [])]),
        "rent":      _dedup_providers([fmt(p) for p in us.get("rent", [])]),
    }


@router.post("/add", response_model=ShowResponse)
async def add_show(body: ShowAddRequest, db: Session = Depends(get_db)):
    """
    Add a show to the local DB. Idempotent — returns existing record if already tracked.
    Fetches canonical title and poster from TMDB.
    """
    if body.user_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"user_status must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

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
        user_status=body.user_status,
        type=body.type,
        added_at=datetime.now(timezone.utc).isoformat(),
        first_air_date=details.get("first_air_date"),
    )
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.patch("/{tmdb_id}/status")
def update_show_status(tmdb_id: int, body: ShowStatusRequest, db: Session = Depends(get_db)):
    """Update the user's personal tracking status for a show."""
    if body.user_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"user_status must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")

    show.user_status = body.user_status
    db.commit()
    return {"tmdb_id": tmdb_id, "user_status": show.user_status}


@router.patch("/{tmdb_id}/pace")
def update_show_pace(tmdb_id: int, body: ShowPaceRequest, db: Session = Depends(get_db)):
    """Set the binge-pace preference for a tracked show."""
    if body.watch_pace not in _VALID_PACES:
        raise HTTPException(
            status_code=422,
            detail=f"watch_pace must be one of: {', '.join(sorted(_VALID_PACES))}",
        )
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")
    show.watch_pace = body.watch_pace
    db.commit()
    return {"tmdb_id": tmdb_id, "watch_pace": show.watch_pace}


@router.post("/{tmdb_id}/wikis")
def add_show_wiki(tmdb_id: int, body: WikiRequest, db: Session = Depends(get_db)):
    """Add a custom wiki link to a tracked show."""
    show = db.execute(
        select(models.Show).where(models.Show.tmdb_id == tmdb_id)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not tracked")
    for u in [body.url, body.season_url_template]:
        if u and not u.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="URLs must start with http:// or https://")
    wiki = models.ShowWiki(
        show_tmdb_id=tmdb_id,
        label=body.label.strip(),
        url=body.url.strip(),
        season_url_template=body.season_url_template.strip() if body.season_url_template else None,
    )
    db.add(wiki)
    db.commit()
    db.refresh(wiki)
    return {"id": wiki.id, "label": wiki.label, "url": wiki.url, "season_url_template": wiki.season_url_template}


@router.delete("/{tmdb_id}/wikis/{wiki_id}")
def delete_show_wiki(tmdb_id: int, wiki_id: int, db: Session = Depends(get_db)):
    """Remove a custom wiki link from a show."""
    wiki = db.execute(
        select(models.ShowWiki).where(
            models.ShowWiki.id == wiki_id,
            models.ShowWiki.show_tmdb_id == tmdb_id,
        )
    ).scalar_one_or_none()
    if not wiki:
        raise HTTPException(status_code=404, detail="Wiki not found")
    db.delete(wiki)
    db.commit()
    return {"deleted": wiki_id}


@router.get("", response_model=list[ShowResponse])
def list_shows(db: Session = Depends(get_db)):
    """List all tracked shows with episode progress, ordered by most recently watched first."""
    rows = db.execute(
        select(
            models.Show,
            func.count(models.Episode.id).label("total_count"),
            func.sum(case((models.Episode.watched == True, 1), else_=0)).label("watched_count"),
        )
        .where(models.Show.type == "tv")
        .outerjoin(models.Episode, models.Episode.tmdb_show_id == models.Show.tmdb_id)
        .group_by(models.Show.id)
        .order_by(models.Show.last_watched_at.desc().nulls_last())
    ).all()

    result = []
    for show, total, watched in rows:
        show.total_count = total or 0
        show.watched_count = watched or 0
        result.append(show)
    return result
