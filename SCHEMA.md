# SCHEMA.md — Where Have I Seen Them?

## shows
| column | type | notes |
|---|---|---|
| id | INTEGER PK | local ID |
| tmdb_id | INTEGER UNIQUE | TMDB show ID |
| title | TEXT | |
| poster_path | TEXT | from TMDB |
| status | TEXT | `watching`, `watchlist`, `finished` |
| type | TEXT | `tv`, `movie` |
| added_at | TEXT | ISO 8601 |
| last_watched_at | TEXT | updated on episode mark |

## episodes
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| show_id | INTEGER FK → shows.id | |
| tmdb_show_id | INTEGER | denormalized for fast joins |
| season_number | INTEGER | |
| episode_number | INTEGER | |
| title | TEXT | |
| air_date | TEXT | ISO 8601, from TMDB |
| watched | BOOLEAN | default false |
| watched_at | TEXT | ISO 8601, null if unwatched |

Unique constraint: `(tmdb_show_id, season_number, episode_number)`

## people
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| tmdb_id | INTEGER UNIQUE | |
| name | TEXT | |
| profile_path | TEXT | |
| credits_cached_at | TEXT | when filmography was last fetched |

## person_credits
Cached filmography — all known credits for a person, not just what user has watched.

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| person_tmdb_id | INTEGER FK → people.tmdb_id | |
| show_tmdb_id | INTEGER | |
| title | TEXT | |
| character | TEXT | |
| type | TEXT | `tv`, `movie` |

## show_cast
Junction between a specific show and its cast members.

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| show_tmdb_id | INTEGER | |
| person_tmdb_id | INTEGER | |
| character | TEXT | |
| order | INTEGER | billing order |

---

## Key Query: "Where Have I Seen Them?"

```sql
SELECT pc.title, pc.character, pc.type
FROM person_credits pc
WHERE pc.person_tmdb_id = :person_id
  AND pc.show_tmdb_id IN (
    SELECT DISTINCT tmdb_show_id FROM episodes WHERE watched = 1
  )
ORDER BY pc.title;
```

## Key Query: Today's Schedule

```sql
-- New episodes airing today/this week
SELECT s.title, e.season_number, e.episode_number, e.air_date
FROM episodes e
JOIN shows s ON s.tmdb_id = e.tmdb_show_id
WHERE e.watched = 0
  AND e.air_date <= date('now')
  AND s.status = 'watching'
ORDER BY s.last_watched_at ASC;
```
