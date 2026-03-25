# PLAN.md — Where Have I Seen Them?

## MVP Goal
A working local web app where you can:
- Track shows (watching, watched, want to watch)
- Mark episodes as watched
- Look up a show's cast and see what else they've been in that you've watched
- Get a daily schedule suggestion

---

## What's Next

**Phase 8 (UI Refresh) — remaining:**
1. Schedule page layout redesign
2. Library page layout redesign
3. Mobile-responsive layout polish
4. Show years on library poster cards and show page (first air year / year range)

**Bugs & improvements:**
- Mark a whole show as complete
- "Mark Season Watched" doesn't support a second watch (rewatch flow)
- Import old watchlists from Trakt
- [x] Episode caching: `_cache_season` always upserts missing episodes from TMDB; `POST /admin/refresh-episodes` backfills all shows

---

## Completed Phases

### Phase 1 — Foundation ✓
- [x] Project scaffold (FastAPI + SQLAlchemy + SQLite)
- [x] `.env` config loading
- [x] TMDB API client with basic search and show fetch
- [x] DB models and migrations
- [x] `POST /shows/search`, `POST /shows/add`, `GET /shows`

### Phase 2 — Episode Tracking ✓
- [x] Fetch and cache episode lists from TMDB
- [x] `POST /episodes/watched` — single episode
- [x] `POST /episodes/watched/bulk` — full season
- [x] `GET /shows/{id}/progress`

### Phase 3 — "Where Have I Seen Them?" ✓
- [x] `GET /shows/{id}/cast` with local caching
- [x] `GET /people/{id}/seen-in` — credits ∩ watch history
- [x] Cast grid with "seen in N" badges; click actor → person page

### Phase 4 — Daily Schedule ✓
- [x] `GET /schedule/today` — airing now / keep watching / up next / pick up again
- [x] Air date awareness, binge progress, "not watched recently" nudges

### Phase 5 — Import & Polish ✓
- [x] Trakt JSON importer
- [x] Full frontend (schedule, library, show/season/episode/person pages)
- [x] Watch providers with deduplication and preferred-service highlighting
- [x] Docker compose

---

## Phase 6 — Library & Status Overhaul ✓

### Status taxonomy redesign ✓
Replace the 4-bucket system with 5 stored statuses that reflect user intent.

Stored user statuses (5):
- `airing`    — following a show that is still releasing new episodes
- `watching`  — working through a completed show at own pace (first time or rewatch)
- `finished`  — completed watching
- `watchlist` — intend to start someday
- `abandoned` — gave up on it

- [x] `backend/main.py`: status migration SQL
- [x] `backend/routers/shows.py`: update `_VALID_STATUSES`
- [x] `backend/routers/schedule.py`: replace `"binging"` with `"watching"`
- [x] `backend/import_trakt.py`: replace `"done"` with `"finished"`
- [x] Frontend: `STATUS_LABEL`, library sections, show status buttons

### Multiple watch dates ✓
- [x] `watch_history` table with full per-episode history
- [x] Season page: `×N` badge + watch-history popover
- [x] Episode page: "+ Log Rewatch" + watch history section with delete

### Progress bars ✓
- [x] Watched/total counts on `GET /shows`; segmented bars on poster cards, season rows, season header

### Other library improvements ✓
- [x] Search/filter bar
- [x] Sort options: last watched, A→Z, Z→A, progress ↓, progress ↑

---

## Phase 7 — Schedule Improvements ✓

### Currently-airing logic ✓
- [x] Schedule starts from the highest season with ≥1 watched episode (active season floor)
- [x] Skips old unstarted seasons; falls back to S1 for new shows

### Binge pace control ✓
Three modes settable per-show: **Binge** (no limit), **Fast** (1–2 eps/session), **Weekly** (~once a week)
- [x] `watch_pace` column on shows; pace buttons on show page
- [x] Schedule respects pace when selecting the episode count to surface

### Daily cap ✓
- [x] Configurable total-episode limit; schedule stops adding after hitting the cap

### Staleness filtering ✓
- [x] `airing`/`watching` idle 3+ months hidden from schedule
- [x] `watching` idle 6+ months auto-abandoned on schedule load

### Other schedule items
- [ ] Upcoming episode calendar — what's airing this week/month
- [ ] Option to dismiss a show from today without abandoning it

---

## Phase 8 — Mobile & UI Refresh

### Design direction: Obsidian / Raycast aesthetic
Dark, precise, slightly techy. Per-page accent colors stay (orange=schedule, yellow=library, etc.).
Screenshot automation: `uv run python scripts/screenshot.py` (requires app running + playwright installed).

### Overall look & feel ✓
- [x] Geist + Geist Mono fonts — Geist Mono for codes, dates, counts, badges
- [x] Section headers → uppercase small-caps labels (0.8rem, tx-dim, bottom border)
- [x] Max-width 960px, nav bar 52px with frosted glass
- [x] Schedule cards: left accent-colored border (Raycast tick)
- [x] Episode rows: tighter padding, lighter separators, recessed unchecked checkbox
- [x] Poster cards: hover lift, border-radius 10px, 2px progress bar
- [x] Seen-in section: inset glow, uppercase label
- [x] Badges/chips unified: round-rect (6px), Geist Mono
- [x] Playwright screenshot script: `scripts/screenshot.py`

### Page-specific redesigns
- [x] Schedule page layout — accent pace badge, ep code in Geist Mono, today's date in header, stepper cap control
- [x] Library page layout — year and episode count on poster cards, 2-line title clamp
- [x] Show page — blue accent title, TMDB link, round-rect status/pace buttons, 4-line overview clamp
- [x] Season page — prev/next season nav, air date inline with ep code, accent left border on watched rows
- [x] Episode page — hero (still + info, 240px thumb), prev/next nav (cross-season), TMDB link, watch history toggle
- [x] Person page — accent title, split seen-in (main/guest), guest episode links, year on all credits

### Other items
- [ ] Mobile-responsive layout polish
- [ ] Possibly installable as PWA (revisit when mobile layout solid)
- [x] Show years on library poster cards — year added to poster cards; show page already shows year range in meta line
- [x] Replace horizontal-scroll cast grids with wrapping grid (global)
- [x] Watch History hidden behind toggle button with prefetched count

---

## Phase 9 — Content Enrichment

- [ ] Actor ages at time of filming (season air year − birth year)
- [x] Movie tracking (DB schema already supports it)
- [ ] External links — TMDB, IMDb, Wikipedia, Rotten Tomatoes on show/person pages
- [ ] Genre and network metadata for filtering

---

## Phase 10 — Watchlist & Discovery

- [ ] Watchlist — shows to check out, not yet tracking
- [ ] "Movie night" picks — shared list for choosing together

---

## Phase 11 — Stats & Data

- [ ] Watch statistics: total hours, shows per year, episodes per week, etc.
- [ ] Completion rates, longest streaks, most-watched genres/networks
- [ ] Data export (CSV or JSON) for backup

---

## Other Features

- [x] On a person page, divide seen-in into main cast vs guest
- [x] If a guest, link to the specific episode (with background backfill on first visit)
- [x] Fix Add to Library 500 Internal Server Error
- [ ] Import old watchlists from Trakt
- [ ] Mark a whole show as complete
- [ ] "Mark Season Watched" can't handle a second watch (rewatch flow)
- [ ] Identify episodes as show premiere, finale, season premiere, mid-season finale, season finale
- [ ] Identify shows on hiatus (mid-season or between-season)
- [ ] Mark an episode as dismissed. (probably won't watch it. no need to suggest it)
- [ ] Links on person page
- [x] All of the page titles are just WHIST so going back in my history isn't useful.
- [ ] Shows on a people page that aren't in my library should link to TMDB
- [ ] Mark an entire show or season as watched with no date

## Out of Scope
- Multiple user accounts
- Social/sharing features
- Public recommendations engine
- Show/episode ratings (user won't use them)
