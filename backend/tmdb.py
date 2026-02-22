import httpx

from backend.config import settings

TMDB_BASE = "https://api.themoviedb.org/3"

_client = httpx.AsyncClient(
    base_url=TMDB_BASE,
    timeout=10.0,
)


async def search_tv(query: str) -> list[dict]:
    """GET /search/tv?query={title}"""
    r = await _client.get(
        "/search/tv",
        params={"query": query, "api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json().get("results", [])


async def get_show(tmdb_id: int) -> dict:
    """GET /tv/{tmdb_id}"""
    r = await _client.get(
        f"/tv/{tmdb_id}",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()


async def get_show_credits(tmdb_id: int) -> dict:
    """GET /tv/{tmdb_id}/credits — returns {cast: [...], crew: [...]}"""
    r = await _client.get(
        f"/tv/{tmdb_id}/credits",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()


async def get_person(tmdb_person_id: int) -> dict:
    """GET /person/{person_id}"""
    r = await _client.get(
        f"/person/{tmdb_person_id}",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()


async def get_season(tmdb_id: int, season_number: int) -> dict:
    """GET /tv/{tmdb_id}/season/{season_number}"""
    r = await _client.get(
        f"/tv/{tmdb_id}/season/{season_number}",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()


async def get_person_credits(tmdb_person_id: int) -> dict:
    """GET /person/{person_id}/combined_credits — tv + movie in one call"""
    r = await _client.get(
        f"/person/{tmdb_person_id}/combined_credits",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()


async def get_episode_credits(tmdb_id: int, season_number: int, episode_number: int) -> dict:
    """GET /tv/{tmdb_id}/season/{season}/episode/{episode}/credits — cast + guest_stars"""
    r = await _client.get(
        f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/credits",
        params={"api_key": settings.tmdb_api_key},
    )
    r.raise_for_status()
    return r.json()
