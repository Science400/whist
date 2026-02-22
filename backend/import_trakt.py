#!/usr/bin/env python3
"""
Trakt watched-shows.json importer.

Usage:
    uv run python backend/import_trakt.py /path/to/watched-shows.json

The script is safe to re-run — shows and episodes already in the DB are
skipped, and already-watched episodes are left unchanged.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from backend.database import Base, SessionLocal, engine
from backend import models, tmdb
from backend.routers.episodes import _ensure_episodes_cached

# TMDB statuses that mean the show is still airing
_ACTIVE_STATUSES = {"Returning Series", "In Production", "Planned", "Pilot"}


async def import_trakt(filepath: str) -> None:
    Base.metadata.create_all(bind=engine)

    data = json.loads(Path(filepath).read_text())
    db = SessionLocal()

    total = len(data)
    print(f"Found {total} shows in {filepath}\n")

    imported = skipped = total_eps = 0

    for i, entry in enumerate(data, 1):
        meta   = entry["show"]
        tmdb_id = meta["ids"].get("tmdb")
        title  = meta.get("title", "Unknown")

        if not tmdb_id:
            print(f"  [{i:>3}/{total}] SKIP  {title}  (no TMDB ID)")
            skipped += 1
            continue

        print(f"  [{i:>3}/{total}] {title}", end="", flush=True)

        # ── 1. Add show to DB if not already tracked ────────────────────────
        show = db.execute(
            select(models.Show).where(models.Show.tmdb_id == tmdb_id)
        ).scalar_one_or_none()

        if not show:
            try:
                details = await tmdb.get_show(tmdb_id)
                tmdb_status = details.get("status", "Ended")
                show = models.Show(
                    tmdb_id=tmdb_id,
                    title=details.get("name", title),
                    poster_path=details.get("poster_path"),
                    status="watching" if tmdb_status in _ACTIVE_STATUSES else "finished",
                    type="tv",
                    added_at=datetime.now(timezone.utc).isoformat(),
                    last_watched_at=entry.get("last_watched_at"),
                )
                db.add(show)
                db.commit()
                db.refresh(show)
            except Exception as e:
                print(f"  ✗  (TMDB show fetch failed: {e})")
                skipped += 1
                continue
        else:
            # Keep last_watched_at up to date
            trakt_ts = entry.get("last_watched_at")
            if trakt_ts and (not show.last_watched_at or trakt_ts > show.last_watched_at):
                show.last_watched_at = trakt_ts

        # ── 2. Fetch and cache all episodes from TMDB (skipped if cached) ───
        try:
            await _ensure_episodes_cached(show, db)
        except Exception as e:
            print(f"  ✗  (episode fetch failed: {e})")
            skipped += 1
            continue

        # ── 3. Mark watched episodes ────────────────────────────────────────
        marked = 0
        for season in entry.get("seasons", []):
            for ep in season.get("episodes", []):
                record = db.execute(
                    select(models.Episode).where(
                        models.Episode.tmdb_show_id == tmdb_id,
                        models.Episode.season_number == season["number"],
                        models.Episode.episode_number == ep["number"],
                    )
                ).scalar_one_or_none()
                if record and not record.watched:
                    record.watched = True
                    record.watched_at = ep.get("last_watched_at")
                    marked += 1

        db.commit()
        total_eps += marked
        imported += 1
        print(f"  ✓  ({marked} eps)")

    db.close()

    print(f"\n{'─' * 52}")
    print(f"Done.  {imported} shows imported,  {total_eps} episodes marked watched.")
    if skipped:
        print(f"       {skipped} shows skipped (no TMDB ID or fetch error).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python backend/import_trakt.py <watched-shows.json>")
        sys.exit(1)
    asyncio.run(import_trakt(sys.argv[1]))
