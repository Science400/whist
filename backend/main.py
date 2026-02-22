from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from backend.database import Base, engine
from backend.routers import episodes, people, schedule, shows

# Create all tables on startup (idempotent)
Base.metadata.create_all(bind=engine)


def _run_migrations() -> None:
    """Inline schema migrations — safe to re-run on every startup."""
    with engine.connect() as conn:
        # Migration 1: add user_status column if not present, populate from status
        try:
            conn.execute(text("SELECT user_status FROM shows LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE shows ADD COLUMN user_status VARCHAR"))
            conn.execute(text("""
                UPDATE shows
                SET user_status = CASE WHEN status = 'watching' THEN 'airing' ELSE 'done' END
            """))
            conn.commit()

        # Migration 2: backfill any rows that still have NULL user_status
        conn.execute(text("""
            UPDATE shows
            SET user_status = CASE WHEN status = 'watching' THEN 'airing' ELSE 'done' END
            WHERE user_status IS NULL
        """))

        # Migration 3: truncate watched_at timestamps to YYYY-MM-DD
        conn.execute(text("""
            UPDATE episodes
            SET watched_at = substr(watched_at, 1, 10)
            WHERE watched_at IS NOT NULL AND length(watched_at) > 10
        """))
        conn.commit()


_run_migrations()

app = FastAPI(
    title="WHIST — Where Have I Seen Them?",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shows.router)
app.include_router(episodes.router)
app.include_router(people.router)
app.include_router(schedule.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


# SPA fallback — must be after all API routes so they take priority.
# Serves frontend/index.html for every unmatched path (enables client-side routing).
@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse("frontend/index.html")
