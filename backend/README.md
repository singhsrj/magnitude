# Magnitude backend (Phase 3)

Two small FastAPI services, Neon for Postgres, Upstash for Redis.

```
Next.js ──HTTPS──▶ rating-service ──HTTP + X-Internal-Key──▶ problem-service
                    │         │
                    │         └──▶ Upstash Redis   issued problems, profile + daily caches, rate limits
                    └────────────▶ Neon Postgres   players, rounds, daily results
```

| Service | Owns | State |
| --- | --- | --- |
| `services/problem` | Problem generation and the seeded daily set | none (pure compute) |
| `services/rating` | Players, Elo updates, profile, daily progress; the only service the browser talks to | Neon + Upstash |
| `packages/engine` | The game engine in Python, shared by both services | none |

**Why two services?** Generation is stateless CPU work that can scale on its own; ratings are stateful and
need the database. The cost is one extra HTTP hop per round and a second thing to deploy. For one player
a single process would be simpler. This split is deliberate, to practise the architecture.

## Engine parity

`packages/engine` is a line-by-line port of `lib/engine` in the Next.js app, including the seeded
mulberry32 generator, so the same seed gives the same problem in both languages. The frontend produces
golden vectors (`npm run golden` writes `tests/parity/golden.json`) and Python must reproduce them:
240 single problems, 160 sequenced problems on a shared rng, 50 daily-set problems, 120 Elo cases, and skill picks.
If you change the engine in either language, change the other and regenerate the vectors.

## API (rating service)

All routes except sign-up and health need `Authorization: Bearer <token>`. JSON is camelCase, and
`GET /v1/profile` returns exactly the frontend's `Profile` type.

| Method and path | Purpose |
| --- | --- |
| `POST /v1/players` | Create an anonymous player. Returns `{playerId, token}`; the token is shown once, only its SHA-256 is stored. |
| `GET /v1/profile` | Rating, peak, per-skill ratings, streaks, last 200 rounds, per-day counts, daily results. Cached 30s. |
| `POST /v1/rounds/next` | Picks a skill (weaker ones more often) and a target difficulty, asks the problem service, returns the problem **without its answer**. |
| `POST /v1/rounds/answer` | `{problemId, choice, timeMs, localDate}` → correct or not, the revealed values, rating change. One answer per problem. |
| `GET /v1/daily/{date}` | The day's 10 problems (no answers), how many you've answered, and your result if finished. |
| `POST /v1/daily/{date}/answer` | `{index, choice, timeMs}`. Must be answered in order; the 10th records the result. |
| `GET /healthz`, `GET /readyz` | Liveness, and readiness (database, Redis and problem service each reported). |

`date` and `localDate` are the player's own calendar day; the server accepts anything within a day of UTC today.

## What lives where

**Postgres (Neon)** is the source of truth: `players` (rating, peak, streaks, per-skill ratings as JSONB, token hash),
`rounds` (every round, indexed by player and time and by player and local date), `daily_results`.
A partial unique index stops a daily problem being answered twice. Answering takes a `FOR UPDATE`
lock on the player row, so concurrent answers can't corrupt a rating.

**Redis (Upstash)**, every key with a TTL:

| Key | Holds | TTL | If Redis is down |
| --- | --- | --- | --- |
| `prob:{id}` | A problem we issued, with its answer, read with `GETDEL` | 30s | rounds return 503 (can't grade without it) |
| `profile:{player}` | Serialized profile JSON | 30s | falls back to the database |
| `daily:{date}` | The day's problems with answers | 36h | falls back to the problem service |
| `rl:{player}`, `signup:{ip}` | Fixed-window rate-limit counters | 60s / 1h | fails open (requests allowed) |

## Neon and Upstash specifics

- **Two Neon strings.** `DATABASE_URL` is the pooled one (host has `-pooler`) for the running service;
  `DIRECT_DATABASE_URL` is the unpooled one, used only for migrations. The pooler is PgBouncer in transaction
  mode, which breaks asyncpg's prepared-statement cache, so `app/dburl.py` turns it off for `-pooler` hosts.
  It also strips libpq-only options (`sslmode`, `channel_binding`) that asyncpg rejects and enables verified TLS.
- **Cold starts.** Neon can suspend an idle database; the first connection afterwards is slow. The engine uses
  `pool_pre_ping`, a 15s connect timeout and connection recycling.
- **Upstash TLS.** Use the `rediss://` TCP URL, not the REST one. Upstash charges per command, so the rate limiter is
  one pipelined round trip and nothing polls.

## Run it

```bash
cd backend
cp .env.example .env          # fill in the Neon and Upstash strings and a random INTERNAL_API_KEY
docker compose up --build     # problem :8001 (internal), migrate (one-shot), rating :8000
```

Offline, with local Postgres and Redis containers instead of Neon and Upstash:
`docker compose -f docker-compose.yml -f docker-compose.local.yml up --build`

First-run check:

```bash
curl localhost:8000/readyz                                   # {"redis":true,"problem_service":true,"database":true}
curl -X POST localhost:8000/v1/players                       # copy the token
TOKEN=...
curl -H "Authorization: Bearer $TOKEN" localhost:8000/v1/profile
curl -X POST -H "Authorization: Bearer $TOKEN" localhost:8000/v1/rounds/next
```

## Tests

Standard library only (no installs):

```bash
python3 -m unittest discover -s tests/parity -v                                   # engine parity with TypeScript
PYTHONPATH=services/rating:packages/engine python3 -m unittest discover \
  -s services/rating/tests -p "test_pure.py" -v                                   # Neon URL handling + game rules
```

With dependencies (neither suite needs Neon or Upstash: they use SQLite and fakeredis):

```bash
cd services/problem && pip install -r requirements-dev.txt && pytest
cd ../rating        && pip install -r requirements-dev.txt && pytest
```

### Status

Verified when written: the parity and pure suites pass, and a static check found no undefined names or broken
imports. **Not yet run:** the FastAPI, SQLAlchemy and Redis code paths, the pytest suites, the migration and the
Docker images, because the build environment had no network access. Run the two pytest suites first;
they exercise the whole flow (sign-up, rounds, replay protection, profile caching, the daily set, rate limits) and will
surface any small mistakes fastest.

## Known limits

- **Anonymous accounts.** The token lives in the browser; lose it and the player is gone. There is no recovery or login.
- **Time is mostly client-reported.** The server won't accept a time much faster than it observed, but can't prove
  think time. Fine for one player; not for a public leaderboard.
- **Rate limiting fails open** if Redis is down, and sign-up limiting keys on the connecting IP (behind a proxy,
  configure forwarded headers).
- **Daily answers are not time-checked** (the set isn't issued one problem at a time).
- **No refresh of the daily set mid-day**; it follows the player's local date, within one day of UTC.

## Phase 4: connecting the frontend

| Frontend today | Becomes |
| --- | --- |
| `loadProfile` / `saveProfile` in `lib/profile.ts` | `GET /v1/profile`; store the token from `POST /v1/players` in localStorage |
| `begin()` in `hooks/useDuel.ts` | `POST /v1/rounds/next` |
| `answer()` | `POST /v1/rounds/answer`, then show `values` and `delta` from the response |
| `dailyProblem(key, i)` | `GET /v1/daily/{date}` and `POST /v1/daily/{date}/answer` |
