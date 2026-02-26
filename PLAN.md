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
Replace the current 4-bucket system (airing/binging/caught_up/done) with statuses
that reflect real intent. Some display categories are *derived* from stored status
+ watch progress; they don't all need to be stored.

Stored user statuses:
- `watching`   — actively working through it (currently airing OR bingeing)
- `rewatching` — second+ pass; supports multiple watch dates per episode
- `up_next`    — on the list, haven't started
- `abandoned`  — not continuing
- `hiatus`     — waiting for new season / return

Display categories for both library and schedule (derived from status + progress):
1. **Airing — episodes available** (watching + current season has unwatched aired eps + you've started that season)
2. **Airing — caught up** (watching + all aired eps watched)
3. **Airing — not started** (watching + 0 eps watched this season)
4. **Rewatching — episodes available**
5. **Rewatching — caught up**
6. **Finished** (show ended + fully watched)
7. **Abandoned**
8. **Returning — nothing new yet** (hiatus status, or watching but between seasons)

**Migration mapping** (existing → new stored status):
- `airing` → `watching`
- `binging` → `watching`
- `caught_up` → `watching`
- `done` → `watching` (display category "Finished" derived if show ended + fully watched)

**Backend todos:**
- [ ] Write DB migration: update `user_status` values in shows table per mapping above
- [ ] Update `Show` model: replace status enum/validation with new 5-value set
- [ ] Add `derive_display_category(show, tmdb_status, watched, total, latest_season_watched)` helper — returns one of the 8 display categories
- [ ] Update `GET /shows` response to include `display_category` field
- [ ] Update `PATCH /shows/{id}/status` to accept new status values
- [ ] Update schedule router: replace status checks (`airing`, `binging`) with new values

**Frontend todos:**
- [ ] Update `STATUS_LABEL` constant for 5 stored statuses
- [ ] Update library: group sections by `display_category` instead of raw `user_status`
- [ ] Update section colors/labels for all 8 display categories
- [ ] Update show page: replace 4 status buttons with 5
- [ ] Update schedule page: replace status-bucket logic with display category logic

### Multiple watch dates
- The DB currently allows one watched_at per episode. Rewatching needs multiple.
- Add a `rewatch_log` table for secondary watches (keeps primary watch history clean).
- UI: show most recent watch date; log icon to see full history.

**Backend todos:**
- [ ] Add `rewatch_log` table: `(id, tmdb_show_id, season_number, episode_number, watched_at)`
- [ ] Write DB migration to create the table
- [ ] Update `POST /episodes/watched` — if `watched=true` and episode already has `watched=true`, append to `rewatch_log` instead of updating `watched_at`
- [ ] New `GET /shows/{id}/season/{n}/episode/{e}/watch-history` — returns all watch dates (primary + rewatches) in reverse order
- [ ] Update season endpoint to include `rewatch_count` per episode

**Frontend todos:**
- [ ] Season page: show rewatch count badge (e.g. "×3") on multi-watched episode rows
- [ ] Season page: log icon on episode rows that opens a simple watch-history popover
- [ ] Episode detail page: show full watch history list

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
- [ ] Fix Add to Library 500 Internal Server Error

## Out of Scope
- Multiple user accounts
- Social/sharing features
- Public recommendations engine
- Show/episode ratings (user won't use them)
