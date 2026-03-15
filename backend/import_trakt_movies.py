#!/usr/bin/env python3
"""
Trakt watched-movies.json importer.

Usage:
    uv run python backend/import_trakt_movies.py /path/to/watched-movies.json

The script is safe to re-run — movies already in the DB are skipped,
and watched state is only set, never cleared.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from backend.database import Base, SessionLocal, engine
from backend import models, tmdb


async def import_trakt_movies(filepath: str) -> None:
    Base.metadata.create_all(bind=engine)

    data = json.loads(Path(filepath).read_text())
    db = SessionLocal()

    total = len(data)
    print(f"Found {total} movies in {filepath}\n")

    imported = skipped = already = 0

    for i, entry in enumerate(data, 1):
        meta    = entry["movie"]
        tmdb_id = meta["ids"].get("tmdb")
        title   = meta.get("title", "Unknown")

        if not tmdb_id:
            print(f"  [{i:>3}/{total}] SKIP  {title}  (no TMDB ID)")
            skipped += 1
            continue

        watched_at = (entry.get("last_watched_at") or "")[:10]  # YYYY-MM-DD

        print(f"  [{i:>3}/{total}] {title}", end="", flush=True)

        # ── 1. Check if already in DB ────────────────────────────────────────
        movie = db.execute(
            select(models.Show).where(models.Show.tmdb_id == tmdb_id)
        ).scalar_one_or_none()

        if movie:
            # Update watched state if not already marked
            changed = False
            if not movie.watched:
                movie.watched = True
                movie.watched_at = watched_at or None
                movie.user_status = "finished"
                changed = True
            if watched_at and (not movie.last_watched_at or watched_at > movie.last_watched_at):
                movie.last_watched_at = watched_at
                changed = True
            if changed:
                db.commit()
                print(f"  ↻  (updated watched state)")
            else:
                print(f"  –  (already imported)")
            already += 1
            continue

        # ── 2. Fetch from TMDB ───────────────────────────────────────────────
        try:
            details = await tmdb.get_movie(tmdb_id)
        except Exception as e:
            print(f"  ✗  (TMDB fetch failed: {e})")
            skipped += 1
            continue

        movie = models.Show(
            tmdb_id=tmdb_id,
            title=details.get("title", title),
            poster_path=details.get("poster_path"),
            user_status="finished",
            type="movie",
            added_at=datetime.now(timezone.utc).isoformat(),
            first_air_date=details.get("release_date"),
            watched=True,
            watched_at=watched_at or None,
            last_watched_at=watched_at or None,
        )
        db.add(movie)
        db.commit()
        imported += 1
        print(f"  ✓")

    db.close()

    print(f"\n{'─' * 52}")
    print(f"Done.  {imported} movies imported,  {already} already present.")
    if skipped:
        print(f"       {skipped} skipped (no TMDB ID or fetch error).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python backend/import_trakt_movies.py <watched-movies.json>")
        sys.exit(1)
    asyncio.run(import_trakt_movies(sys.argv[1]))
