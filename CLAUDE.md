# Where Have I Seen Them? — Claude Code Instructions

## Project Overview
"Where Have I Seen Them?" (WHIST) is a self-hosted personal TV/movie tracking app replacing Trakt.tv. The two core use cases are:
1. Look up a cast member from something you're watching and instantly see what else they've been in that you've already watched
2. Get a daily watch suggestion schedule mixing new episode air dates and binge progress

Full data ownership. Runs locally on a home network.

## Stack
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, SQLite
- **Frontend:** Plain HTML/JS (no build step preferred for MVP)
- **External API:** TMDB (https://api.themoviedb.org/3)
- **Config:** `.env` file for secrets — never commit

## Project Structure
```
whist/
├── backend/
│   ├── main.py           # FastAPI app entry point
│   ├── database.py       # SQLAlchemy setup + session
│   ├── models.py         # DB models
│   ├── tmdb.py           # TMDB API client (search, fetch, cache)
│   └── routers/
│       ├── shows.py      # Add/search/manage shows
│       ├── episodes.py   # Mark watched, bulk update
│       ├── people.py     # Cast lookup + "seen in" join
│       └── schedule.py   # Daily watch suggestions
├── frontend/
│   └── index.html
├── CLAUDE.md
├── PLAN.md
├── SCHEMA.md
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## Environment Variables
```
TMDB_API_KEY=your_key_here
DATABASE_URL=sqlite:///./whist.db
```

## Key Rules
- TMDB ID is the canonical identifier for all shows, movies, and people — never use titles as keys
- Cache TMDB metadata locally after first fetch to avoid redundant API calls
- All datetimes stored as ISO 8601 UTC
- Episodes identified by `(tmdb_show_id, season_number, episode_number)` tuple
- The "seen in" feature is the most important feature — keep that query fast

## Running Locally
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## Dev Notes
- Test endpoints with curl or Bruno during development
- No formal test suite required for MVP
- Prioritize the cast/history join and schedule endpoints — everything else is CRUD
