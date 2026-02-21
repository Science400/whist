from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import Base, engine
from backend.routers import episodes, people, schedule, shows

# Create all tables on startup (idempotent)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WHIST — Where Have I Seen Them?",
    version="0.1.0",
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


# Serve frontend — must be last so API routes take priority
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
