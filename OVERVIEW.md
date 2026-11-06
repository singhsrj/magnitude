# Magnitude — How It Works

A short guide to the codebase. For setup commands see `README.md` and `backend/README.md`; the Phase 4 design and its
implementation notes are in `PHASE_4.md`.

## What it is

A mental-math speed game. You see two expressions (for example `47 × 23` vs `51 × 21`) and press `←` or `→`
to pick the bigger one. An Elo rating adjusts the difficulty after each round, so you get about 70% right.

Four skills, each with its own rating: **multiplication, percentages, fractions, powers**.

## Architecture

```
┌────────────────────────── Browser: Next.js 15 / React 19 ──────────────────────────┐
│ app/ (routes) → components/ (UI) → hooks/useDuel.ts → lib/engine (pure game logic)  │
│                                          │  every answer                             │
│                                          ▼                                           │
│            lib/profile.ts (local copy)   lib/sync.ts: outbox + tickets (localStorage)│
└───────────────────────────────────────────────┬────────────────────────────────────┘
        no network between a keypress and the   │ background: POST /v1/sessions, POST /v1/sync
        feedback; syncing happens afterwards    ▼
┌──────────────────────── backend/ rating-service (FastAPI) :8000 ────────────────────┐
│ replays each synced round with packages/engine (a Python port of lib/engine)         │
│      ├──▶ Postgres (Neon)   players, sessions, rounds, daily results (source of truth)│
│      └──▶ Redis (Upstash)   profile cache, rate limits (best-effort)                  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**The browser plays; the server verifies.** Problems, grading and Elo run in the browser, so a round feels
instant. The server hands out a seed per session ahead of time, then rebuilds every problem from that seed with its
own copy of the engine, grades your answers itself, and applies Elo to the authoritative rating. With
`NEXT_PUBLIC_SYNC` off, none of the backend is used and everything stays in `localStorage`.

## Frontend

| Path | Role |
| --- | --- |
| `app/page.tsx` → `/` | Home dashboard: rating chart, skill ratings, daily set card, last 20 rounds, 14-day activity strip |
| `app/duel/page.tsx` → `/duel` | Endless practice rounds |
| `app/duel/daily/page.tsx` → `/duel/daily` | 10-problem daily set, the same for everyone on a given date |
| `components/ui/` | Small shared pieces: `KeyCap`, `StatPill`, `Logo` |
| `components/duel/` | `DuelScreen`, `ExprCard`, `TimerBar`, `DailySummary` |
| `components/home/` | Dashboard cards (`RatingCard` + `RatingChart`, `SkillsCard`, `DailyCard`, `RecentCard`) and `SyncPill` (shown only when rounds can't be saved) |
| `hooks/useDuel.ts` | The game state machine: `loading → question → result → question …` (daily mode ends at `summary`). Takes a session ticket, builds problems from its seed, grades, saves locally, records each answer in the outbox |
| `lib/profile.ts` | The local copy of the profile (localStorage), migrating older versions. A cache when sync is on |
| `lib/api.ts`, `lib/auth.ts` | `fetch` wrapper with typed errors; the anonymous account token (and the one-time import of old local progress) |
| `lib/sync.ts` | Session tickets, the outbox, the flush scheduler (every 5 answers, on leaving, when the tab hides, when back online), reconcile |
| `lib/reconcile.ts` | Pure: *local profile = server profile + rounds the server hasn't acknowledged yet* |
| `lib/format.ts` | Number and time formatting |

Styling uses Tailwind, with design tokens taken from the Figma file "Magnitude — UI/UX".

### `lib/engine/`: the core logic (no React)

- **`elo.ts`**: Elo rating that also rewards speed. Each round scores 0 to 1:
  - wrong or timed out (8s limit): 0
  - correct: 0.70 + 0.30 × speed, where speed runs linearly from 6s (slowest) to 0.8s (fastest)
  - `delta = 24 × (score − expected)`, with `expected = 1 / (1 + 10^((problem − player)/400))`
  - `normalizeTime()` turns a think time into whole ms between 250 and 8000; client and server both use it first
- **`problems.ts`**: Builds a pair of expressions per skill and gives it a difficulty rating from two factors:
  how big the numbers are and how close the two values are. It creates candidates until one is close to the target rating.
- **`session.ts`**: `applyRound` updates the overall and per-skill ratings, streaks, peak and history, and handles
  profile migration. Also `pickSkill`, and the practice-session functions: `sessionProblem(seed, index, skills)` and
  `nextGenSkills`. Each round has its own generator derived from `(seed, index)`, and skills are rounded to whole numbers
  before a problem is chosen, so float noise can't make the two languages disagree.
- **`stats.ts`**: the rating series for the chart, the weakest skill and the day streak.
- **`daily.ts`**: Builds the daily set from a seed based on the date, with difficulty rising across the 10 problems.
- **`rng.ts`**: mulberry32, a seeded random number generator, so a given seed always produces the same problems.

### One round, step by step

1. `useDuel` builds the problem from the session's seed, the round index and the session's generation skills.
2. The timer starts. The player presses a key, or the round times out after 8s.
3. The game grades the answer and runs `applyRound` for the overall and skill ratings. The result shows immediately.
4. The answer is appended to the outbox (localStorage) and the profile is saved. A sync starts in the background after 5 answers.

## Backend (`backend/`)

| Part | Role |
| --- | --- |
| `packages/engine/magnitude_engine` | Python port of `lib/engine`, line by line, including mulberry32 and JS-style maths (`jsmath.py`) |
| `services/rating` | The API: anonymous players (bearer token, only its SHA-256 is stored), sessions, sync, profile. SQLAlchemy async + Alembic migrations |
| `services/problem` | The old stateless problem generator. **Retired in Phase 4**: not in Docker Compose and not on any request path, kept in the repo only as a small standalone service |
| `tests/parity/` | `golden.json` is produced by `npm run golden`. Python must reproduce it exactly (problems, sessions, 60-round replays, Elo) |
| `docker-compose*.yml` | Containers for migrate (one-shot) and rating. The `.local` override adds local Postgres and Redis |

**API:** `POST /v1/players` (optionally with an old browser profile to import once) → `POST /v1/sessions` (a ticket:
session id + seed) → `POST /v1/sync` (a batch of up to 200 answers). Sync is one transaction with the player row locked.
For each answer the server rebuilds the problem and **rejects it if the browser's `problemId`/`problemRating` differ**,
grades it from the choice (the browser's `correct` is ignored), checks timing (no faster than 250 ms, think times can't
exceed the real time elapsed, answers can't be from the future or from before the ticket was issued) and applies Elo.
Duplicates are acknowledged without being applied again, which makes retries safe. Rejecting a practice answer breaks
its session; other sessions and daily answers carry on. The response is the authoritative profile.

Other safeguards: rate limits (Redis), `/readyz` checks the database and Redis, the Neon pooler URL is adjusted for asyncpg.

## Scripts

| Command | Does |
| --- | --- |
| `npm run dev` | Starts the app at http://localhost:3000 |
| `npm run verify:engine` | Sanity checks for Elo, the generator, sessions and reconcile, plus simulated players |
| `npm run golden` | Regenerates the backend parity test vectors |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run e2e:sync` | Plays 250 rounds (online, offline, lost response) through the real sync code against a running backend and compares the server's profile with an independent local computation |
| `node scripts/e2e-browser.mjs` | Same idea in real Chrome over the DevTools Protocol: no request during a round, background syncs, offline, daily set (`--sync-off` checks the no-backend mode) |

## Status and roadmap

- Phases 0–2 are done: a playable frontend with dashboard, daily set and mobile layouts.
- Phase 3: the backend. Its test suites and Docker images have now been run (they found two small test bugs, fixed).
- Phase 4 is done: the UI plays locally and syncs in the background, and the server verifies by replay. Checked with the
  parity tests (exact problem equality over 1,200 session problems and six 60-round replays), 49 SQLite tests, 4 tests
  against real Postgres (including concurrent syncs), the Node e2e (10 runs in a row) and the Chrome e2e.
- Still open from Phase 4: calibrating difficulty from real play data (see Known limits below).
- Phase 5: deploy to AWS (ECS + a scheduled Lambda), plus CI and metrics.

**Known limits:** Above about 1600–1800 the generator's problems get easier than the target. Because a correct answer
always scores at least 0.70, ratings settle a little low. Accounts are anonymous with no way to recover them. Answer times
are client-reported (bounded by the server's checks, enough for one player, not for a public leaderboard). "Reset
progress" is hidden when sync is on, because the server holds the real profile and there is no server-side reset yet.
