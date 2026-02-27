# PLAN.md — Where Have I Seen Them?

## MVP Goal
A working local web app where you can:
- Track shows (watching, watched, want to watch)
- Mark episodes as watched
- Look up a show's cast and see what else they've been in that you've watched
- Get a daily schedule suggestion

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

## Phase 6 — Library & Status Overhaul (next up)

### Status taxonomy redesign
Replace the 4-bucket system with 5 stored statuses that reflect user intent.
Key split: **airing** = show still releasing, follow on its schedule;
**watching** = show complete/far behind, work through at own pace.
Derived sub-categories (On Hiatus, Airing — caught up, etc.) deferred to Phase 7.

Stored user statuses (5):
- `airing`    — following a show that is still releasing new episodes
- `watching`  — working through a completed show at own pace (first time or rewatch)
- `finished`  — completed watching
- `watchlist` — intend to start someday
- `abandoned` — gave up on it

Note: "hiatus" is derived (not stored) — airing + caught up + no new eps = between seasons.

**Migration mapping** (existing → new):
- `airing`    → `airing`
- `caught_up` → `airing`    (caught up = still following an airing show)
- `binging`   → `watching`  (binging a completed show = watching)
- `done`      → `finished`  (done = finished watching)

**Backend todos:**
- [x] `backend/main.py`: add startup migration SQL (safe to re-run; WHERE clause scoped to old values)
- [x] `backend/routers/shows.py`: update `_VALID_STATUSES` to `{"airing","watching","finished","watchlist","abandoned"}`
- [x] `backend/routers/schedule.py`: replace `"binging"` with `"watching"` (3 occurrences)
- [x] `backend/import_trakt.py`: replace `"done"` with `"finished"` in auto-status assignment
- [x] `backend/models.py`: update `user_status` column comment

**Frontend todos:**
- [x] Update `STATUS_LABEL` constant (5 entries; `watchlist` and `finished` replace old values)
- [x] `pageLibrary()`: update groups dict, order, and section colors for 5 sections
- [x] `pageShow()`: status buttons update automatically from `STATUS_LABEL` (no structural change)

### Multiple watch dates ✓
- Unified `watch_history` table holds every watch instance — no primary/secondary distinction.
- `episodes.watched` + `episodes.watched_at` kept as a denormalized cache for fast queries.
- UI shows most recent date; pencil/history icon opens full history.

**Backend todos:**
- [x] Add `watch_history` table: `(id, tmdb_show_id, season_number, episode_number, watched_at)`
- [x] Migration 5: create table + backfill from existing `episodes.watched_at` (idempotent)
- [x] Update `POST /episodes/watched` — always appends to `watch_history` (supports rewatches); `watched=false` clears all history entries
- [x] New `GET /shows/{id}/season/{n}/episode/{e}/watch-history` — all watch dates newest-first
- [x] New `DELETE /episodes/history/{id}` — remove single entry, re-syncs episode state
- [x] Update season endpoint to include `watch_count` and most-recent `watched_at` per episode

**Frontend todos:**
- [x] Season page: `×N` badge on multi-watched episode rows
- [x] Season page: pencil on watched row opens watch-history popover (list + add/delete)
- [x] Episode detail page: "+ Log Rewatch" button + watch history section with delete

### Progress bars ✓
- [x] `GET /shows` includes watched/total episode counts per show
- [x] Poster cards show segmented episode bars (lazy-loaded)
- [x] Season rows on show page show segmented episode bars
- [x] Season page header bar segmented; toggles live on check/uncheck

### Other library improvements
- [x] Search/filter bar
- [x] Sort options: last watched, A→Z, Z→A, progress ↓, progress ↑
- [x] Episode progress bars on poster cards

---

## Phase 7 — Schedule Improvements

### Currently-airing logic
- Only show a show's episodes if you've *started* the current season.
  If there are 6+ unwatched aired episodes and you haven't started, skip it —
  you're not ready to catch up yet. Surface it in "Airing — not started" instead.
- Once you start a season, show the unwatched aired episodes up to the current one.

### Binge pace control (for completed shows and rewatches)
Three modes settable per show:
- **Binge** — show as many as feel right, no limit
- **Fast** — surface it every session, 1–2 eps
- **Weekly** — appear roughly once a week

### Daily cap
- Configurable total episode limit for the day's schedule
- When the cap is hit, stop adding more — prevents overwhelming queues
- Shows near the cap threshold get priority by last-watched date

### Active season floor ✓
- Schedule surfaces episodes from the highest season the user has started (≥1 watched ep),
  skipping old unstarted seasons automatically. Falls back to S1 for brand-new shows.

### Staleness filtering ✓
- `airing` and `watching` shows idle for 3+ months are hidden from the schedule.
- `watching` shows idle for 6+ months are auto-switched to `abandoned` on schedule load.
- Timestamp format handled: `last_watched_at` stored as full ISO string, sliced to `YYYY-MM-DD` for comparison.

### Other schedule items
- [ ] Upcoming episode calendar — what's airing this week/month
- [ ] Option to dismiss a show from today without abandoning it

---

## Phase 8 — Mobile & UI Refresh

- [ ] Mobile-responsive layout (works well on phone)
- [ ] Possibly installable as PWA (home screen shortcut; not ideal since it doesn't
      go to app drawer on Android — revisit when mobile layout is solid)
- [ ] Replace horizontal-scroll cast grids with wrapping grid option. This is because the actor and character names get cut off easily.
- [ ] Visual redesign — less utilitarian
- [ ] Show years in the appropriate places
- [ ] Watch History should be hidden utill asked for, ie not front and center on the page.

---

## Phase 9 — Content Enrichment

- [ ] Actor ages at time of filming (season air year − birth year)
- [ ] Movie tracking (DB schema already supports it)
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

## Other Features (To Be Categorized)
- [ ] On a person page, divide their things I've seen them in into main character vs guest
- [ ] If they're a guest, link to the specific episode
- [ ] Fix Add to Library 500 Internal Server Error
- [ ] Import old watchlists from Trakt

## Out of Scope
- Multiple user accounts
- Social/sharing features
- Public recommendations engine
- Show/episode ratings (user won't use them)
