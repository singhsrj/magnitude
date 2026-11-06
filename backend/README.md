# Magnitude backend

One FastAPI service (`services/rating`), Neon for Postgres, Upstash for Redis.

```
Browser ──HTTPS──▶ rating-service ──▶ Neon Postgres   players, sessions, rounds, daily results
 (plays offline,        │
  syncs in batches)     └──▶ Upstash Redis   profile cache, rate limits (both best-effort)
```

| Part | Owns | State |
| --- | --- | --- |
| `services/rating` | Players, practice sessions, replay and verification of synced rounds, profile | Neon + Upstash |
| `packages/engine` | The game engine in Python, shared with the rating service | none |
| `services/problem` | The old stateless problem generator. **Retired in Phase 4**: not in Docker Compose, not on any request path. Kept in the repo as a small standalone service; its tests still run | none |

## How play works (Phase 4)

The browser plays from a seed and never waits on this service during a round. Later it sends what happened and the
server replays it.

1. `POST /v1/sessions` → `{sessionId, seed, expiresAt}`. The browser keeps a couple of these in reserve.
2. The browser builds every problem from `(seed, round index, generation skills)` with its copy of the engine, grades
   locally and keeps the answers in an outbox.
3. `POST /v1/sync` with up to 200 answers. For each one the server rebuilds the same problem with `packages/engine`,
   grades the answer itself, applies Elo to the player row, stores the round, and returns the authoritative profile.

Why this and not "ask the server for each problem": a round trip per round (plus a database write) made the game feel
slow, and hiding the answer on the server protected nothing, because both expressions are on screen. What can
actually be cheated is timing, which the server can only bound (see below).

### What a sync checks

- **The problem.** The event carries the `problemId` and `problemRating` the browser saw. If the rebuilt problem differs,
  the event is rejected with `mismatch`, the session is marked broken, and an ERROR is logged (that means an engine
  parity bug or tampering).
- **Grading.** From `choice` only. The browser's `correct` flag is ignored.
- **Order.** A session's rounds must arrive as 0, 1, 2…; anything else is a `gap`. Duplicates are acknowledged and not
  applied again, so retries are safe. Daily answers follow the same rule per date.
- **Time.** `timeMs` is normalized exactly like the client does (whole ms, 250 to 8000). A session's think times can't
  add up to more than the wall-clock time between its first and last answer (plus 2 s per round). Answers can't be from
  the future (60 s slack) or from before the ticket was issued. The player's local date must be within a day of the UTC
  date of the answer. Daily answers can't be older than 7 days.
- **Starting skills.** Round 0 declares the skills the session started from; they must be within 300 of the server's
  (they only steer difficulty).
- Rejecting a practice event breaks its session, since later rounds depend on it. Other sessions and daily answers
  in the same batch carry on.

Rejection reasons: `unknown_session`, `expired`, `session_broken`, `gap`, `mismatch`, `bad_start`,
`implausible_time`, `bad_date`, `out_of_range`.

## Engine parity

`packages/engine` is a line-by-line port of `lib/engine` in the Next.js app, including the seeded
mulberry32 generator, so the same seed gives the same problem in both languages. The frontend produces
golden vectors (`npm run golden` writes `tests/parity/golden.json`) and Python must reproduce them: single problems,
sequenced problems on a shared rng, daily sets, Elo cases, skill picks, per-round generators, `normalizeTime` cases,
**1,200 session problems** and **six scripted 60-round sessions** (same problem, grading, ratings and generation skills
at every step).
If you change the engine in either language, change the other and regenerate the vectors.

## API

All routes except sign-up and health need `Authorization: Bearer <token>`. JSON is camelCase, and
`GET /v1/profile` returns exactly the frontend's `Profile` type.

| Method and path | Purpose |
| --- | --- |
| `POST /v1/players` | Create an anonymous player. Returns `{playerId, token}`; the token is shown once, only its SHA-256 is stored. The body is optional: `{"import": <Profile>}` takes a pre-Phase-4 browser profile once, unverified. |
| `GET /v1/profile` | Rating, peak, per-skill ratings, streaks, last 200 rounds, per-day counts, daily results. Cached 30s. |
| `POST /v1/sessions` | A practice session ticket `{sessionId, seed, expiresAt}`. 30 per minute per player. |
| `POST /v1/sync` | `{events: [...]}` (1 to 200). Returns `{acked, rejected, profile}`. `acked` includes duplicates. A `409` means a concurrent request conflicted: retry. |
| `GET /healthz`, `GET /readyz` | Liveness, and readiness (database and Redis each reported). |

An event is either `{kind: "practice", sessionId, index, startSkills?, choice, timeMs, at, localDate, problemId, skill, problemRating, correct}`
or `{kind: "daily", date, index, choice, timeMs, at, problemId, skill, problemRating, correct}`. `startSkills` goes with index 0 only.

### Importing an old profile

`POST /v1/players` with `{"import": <Profile>}` carries progress made before Phase 4. It's accepted once, at account
creation (`players.imported`), and can't be checked, so it's range-validated only. Each history record needs the
player's own calendar day (`localDate`), which only the browser can compute. History becomes `rounds` rows. Days that the
last 200 rounds don't cover get placeholder rows (`mode = 'imported'`), which keep the heat strip and day streak intact and
are ignored by the profile's history.

## What lives where

**Postgres (Neon)** is the source of truth: `players` (rating, peak, streaks, per-skill ratings as JSONB, token hash),
`sessions` (seed, generation skills, next expected index, status), `rounds` (every round, indexed by player and time and by
player and local date), `daily_results`. Two partial unique indexes make replays idempotent: `uq_rounds_session`
(`session_id, round_index`) and `uq_rounds_daily` (`player, local_date, daily_index`). A sync takes a `FOR UPDATE` lock on
the player row, so concurrent syncs can't corrupt a rating.

**Redis (Upstash)**, every key with a TTL, nothing required for correctness:

| Key | Holds | TTL | If Redis is down |
| --- | --- | --- | --- |
| `profile:{player}` | Serialized profile JSON | 30s | falls back to the database |
| `rl:{player}`, `sess:{player}`, `signup:{ip}` | Fixed-window rate-limit counters | 60s / 1h | fails open (requests allowed) |

## Neon and Upstash specifics

- **Two Neon strings.** `DATABASE_URL` is the pooled one (host has `-pooler`) for the running service;
  `DIRECT_DATABASE_URL` is the unpooled one, used only for migrations. The pooler is PgBouncer in transaction
  mode, which breaks asyncpg's prepared-statement cache, so `app/dburl.py` turns it off for `-pooler` hosts.
  It also strips libpq-only options (`sslmode`, `channel_binding`) that asyncpg rejects and enables verified TLS.
- **Cold starts.** Neon can suspend an idle database; the first connection afterwards is slow. The engine uses
  `pool_pre_ping`, a 15s connect timeout and connection recycling.
- **Upstash TLS.** Use the `rediss://` TCP URL, not the REST one. Upstash charges per command, so the rate limiter is
  one pipelined round trip and nothing polls.
- **CORS preflight** is cached for a day (`max_age=86400`), otherwise the browser repeats it before every sync.

## Run it

```bash
cd backend
cp .env.example .env          # fill in the Neon and Upstash strings
docker compose up --build     # migrate (one-shot), then rating on :8000
```

Offline, with local Postgres and Redis containers instead of Neon and Upstash:
`docker compose -f docker-compose.yml -f docker-compose.local.yml up --build`

First-run check:

```bash
curl localhost:8000/readyz                                   # {"redis":true,"database":true}
curl -X POST localhost:8000/v1/players                       # copy the token
TOKEN=...
curl -H "Authorization: Bearer $TOKEN" localhost:8000/v1/profile
curl -X POST -H "Authorization: Bearer $TOKEN" localhost:8000/v1/sessions
```

## Tests

Standard library only (no installs). On Windows the `PYTHONPATH` separator is `;`:

```bash
python3 -m unittest discover -s tests/parity -v                                   # engine parity with TypeScript
PYTHONPATH=services/rating:packages/engine python3 -m unittest discover \
  -s services/rating/tests -p "test_pure.py" -v                                   # Neon URL handling + sync plausibility rules
```

With dependencies (a virtualenv is easiest: `python -m venv .venv && .venv/bin/pip install -r services/rating/requirements-dev.txt -r services/problem/requirements-dev.txt -e packages/engine`).
Neither suite needs Neon or Upstash: they use SQLite and fakeredis.

```bash
cd services/rating  && pytest      # sessions, sync, import, profile, limits (SQLite + fakeredis)
cd services/problem && pytest      # the retired service's own tests
```

Against a **real** stack (Postgres row locks, Redis), which SQLite can't show, including concurrent syncs:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
cd services/rating && LIVE_API_URL=http://localhost:8000 pytest tests/test_live.py -v
```

Sign-ups are rate limited per IP (10/hour by default). If a live or e2e run is refused with 429, clear the local counters:
`docker compose -f docker-compose.yml -f docker-compose.local.yml exec redis redis-cli flushall`.

From the repo root, `npm run e2e:sync` and `node scripts/e2e-browser.mjs` drive the real frontend code against this stack.

### Status

Run and passing: parity (11), pure rules (12), rating service (49 on SQLite, 4 more against live Postgres), problem service (9),
the migrations (0001 and 0002 apply, 0002 downgrades and re-applies), the Docker images, and both end-to-end scripts.
The test suites found two small bugs in tests when first run (Windows default encoding when reading the golden file, and a
substring assertion that matched `"answered"`); both are fixed.

## Known limits

- **Anonymous accounts.** The token lives in the browser; lose it and the player is gone. There is no recovery or login.
- **Time is client-reported.** The server bounds it (floor, wall-clock total, no future answers) but can't prove think
  time. Fine for one player; not for a public leaderboard, which would need server-issued seeds every N rounds.
- **Rate limiting fails open** if Redis is down, and sign-up limiting keys on the connecting IP (behind a proxy,
  configure forwarded headers).
- **The client can compute upcoming problems from the seed.** Not an exploit: both expressions are on screen anyway.
- **A midnight edge case.** A daily set started just before local midnight and finished just after is stored under its
  own date, while the browser's heat strip counts rounds by the day each was answered. The server's view wins on the next sync.
- **No server-side reset.** The frontend hides "Reset progress" when sync is on.
