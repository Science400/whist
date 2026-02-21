# PLAN.md — Where Have I Seen Them?

## MVP Goal
A working local web app where you can:
- Track shows (watching, watched, want to watch)
- Mark episodes as watched
- Look up a show's cast and see what else they've been in that you've watched
- Get a daily schedule suggestion

---

## Phase 1 — Foundation
- [ ] Project scaffold (FastAPI + SQLAlchemy + SQLite)
- [ ] `.env` config loading
- [ ] TMDB API client with basic search and show fetch
- [ ] DB models and migrations (see SCHEMA.md)
- [ ] `POST /shows/search` — search TMDB by title
- [ ] `POST /shows/add` — save a show to local DB with status (watching/watchlist/watched)
- [ ] `GET /shows` — list all tracked shows

## Phase 2 — Episode Tracking
- [ ] `GET /shows/{id}/episodes` — fetch and cache episode list from TMDB
- [ ] `POST /episodes/watched` — mark a single episode watched
- [ ] `POST /episodes/watched/bulk` — mark a full season or show watched
- [ ] `GET /shows/{id}/progress` — current season/episode and % complete

## Phase 3 — The Main Feature: "Where Have I Seen Them?"
- [ ] `GET /shows/{id}/cast` — fetch cast from TMDB, cache people locally
- [ ] `GET /people/{id}/seen-in` — given a person's TMDB ID, return all their credits that overlap with the user's watch history
- [ ] Frontend cast page: click an actor → see your overlap instantly

## Phase 4 — Daily Schedule
- [ ] Pull air dates for currently-watching shows from TMDB
- [ ] Identify "new episode today/this week" shows
- [ ] Identify next unwatched episode for binge shows
- [ ] `GET /schedule/today` — returns an ordered suggestion list
- [ ] Basic weighting: prioritize new air dates, then shows not watched recently

## Phase 5 — Import & Polish
- [ ] Trakt export importer (JSON → watch_history bulk insert)
- [ ] Simple frontend for all of the above
- [ ] Docker compose setup for easy hosting

---

## Out of Scope for MVP
- Mobile app
- Multiple user accounts
- Movie tracking (add later — schema supports it)
- Social/sharing features
- Ratings and reviews
