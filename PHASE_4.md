# Phase 4: Connect the UI to the backend without adding latency

This is the implementation spec. Work through the steps in order; each one ends in a state that can be checked.
Background: `OVERVIEW.md`. Backend reference: `backend/README.md`.

> **Status: implemented (steps 0 to 6).** The spec below is kept as written; "Implementation notes" at the end lists
> where the build differs from it and what was and wasn't verified.

## 1. Goal and the rule that drives everything

**Goal:** progress is stored and verified on the server, and the game feels exactly as fast as the browser-only version.

**Rule: nothing between a keypress and the feedback touches the network.** Generating problems, grading answers,
updating Elo and saving locally all happen in the browser, as they do today. The server sees what happened afterwards,
in batches, and checks it by replaying the session with the Python engine.

The first Phase 4 attempt broke this rule. It made two blocking calls per round (`/rounds/next`, `/rounds/answer`),
each adding a hop to the problem service, Redis, and a Postgres lock and commit. Hiding the answer on the server bought
almost nothing, because the player can see both expressions and compute it. Timing is the only thing worth cheating,
and the server could never verify timing anyway.

### Acceptance criteria

- [x] No network request happens while a round is running. *Real Chrome, 12 rounds: no request started between a question
      appearing and the answer (`scripts/e2e-browser.mjs`). The sync an answer triggers starts a few ms after it, on the result screen.*
- [~] Feedback after a keypress takes as long as it does on today's `main` (one frame). *By construction: the answer path
      has no `await` and does only local work (Elo, two localStorage writes). Frame time was not benchmarked.*
- [x] After 50 practice rounds and a daily set, the server profile matches the local one: `rating`, `peak`, `skills`,
      `streak`, `bestStreak`, `rounds` within 1e-9, and `history`, `days`, `daily` equal. *`npm run e2e:sync` compares the
      server's profile with one computed independently from the engine, after 250 rounds: 10 of 10 runs, random seeds.*
- [x] 20 rounds played offline sync automatically when the connection comes back, with nothing lost or duplicated.
      *Node e2e (20 rounds) and Chrome e2e (6 rounds, with the API origin blocked).*
- [~] Closing the tab right after an answer loses nothing. The round syncs on the next visit. *Every answer is in
      localStorage before the result shows, and leftovers are sent at the next start; the keepalive flush on leaving is
      exercised by navigating away. A literal tab close wasn't automated.*
- [~] The dashboard renders from the local cache with no spinner, then refreshes in the background. *By construction
      (`loadProfile()` first, then the server profile replaces it); not measured.*
- [x] With `NEXT_PUBLIC_SYNC` off the app behaves exactly as it does today (no backend needed). *Chrome run with sync off:
      6 rounds saved locally, zero requests to the API, no account, "Reset progress" still shown.*

## 2. Design

```
 Browser                                                     rating-service
 ───────                                                     ──────────────
 dashboard mount ── POST /v1/sessions (×2, background) ───▶  issue {sessionId, seed}
                  ◀── tickets stored in localStorage ──────
 duel: round i  =  sessionProblem(seed, i, genSkills)        (no request)
       answer   →  applyRound locally → outbox.push(event)   (no request)
 every 5 events / leaving the duel / tab hidden:
                  ── POST /v1/sync {events[]} ────────────▶  lock player row
                                                             replay each event with magnitude_engine
                                                             verify, store rounds, apply Elo
                  ◀── {acks, rejects, profile} ───────────   commit, drop profile cache
 reconcile: local = server profile + still-pending events re-applied
```

### 2.1 Sessions and seeds

- A **session** is one visit to `/duel`: an unbounded run of practice rounds, capped at `SESSION_MAX_ROUNDS = 500`.
  A new session starts when that cap is reached.
- `POST /v1/sessions` returns `{sessionId, seed, expiresAt}`. `seed` is a uint32 from `secrets.randbits(32)`.
- The client keeps a **pool of 2 unused tickets** in localStorage and tops it up in the background
  (on dashboard mount, and after a ticket is used). The duel never waits for a ticket unless the pool is empty and
  the device is offline. In that case it shows "Connecting…".
- A ticket that is never used expires after 7 days. Once a session's first round is played, its events are accepted
  for 7 days (to cover offline play).

### 2.2 Deterministic problems per round

Each round gets its own generator, derived from the seed and the round index, using the same pattern as
`dailyProblem`. A bug in one round can't change how many random numbers later rounds draw, and round `i` can be
rebuilt on its own.

```ts
// lib/engine/session.ts (new) — Python mirror in magnitude_engine/session.py
export function roundRng(seed: number, index: number): Rng {
  return mulberry32(seed ^ Math.imul(index + 1, 0x9e3779b1));
}

/** Problem `index` of a practice session. `gen` = the session's generation skills before this round. */
export function sessionProblem(seed: number, index: number, gen: Record<Skill, number>): Problem {
  const rng = roundRng(seed, index);
  const rounded = roundSkills(gen);                       // Math.round each value
  const skill = pickSkill(rng, rounded);
  const target = Math.round(targetProblemRating(rounded[skill]));
  return generateProblem({ skill, targetRating: target, rng });
}

/** Rolls the generation skills forward after a round (floats; rounded only when used). */
export function nextGenSkills(gen, problem, correct, timeMs): Record<Skill, number> {
  return { ...gen, [problem.skill]: updatePlayer(gen[problem.skill], problem.rating, correct, timeMs).next };
}
```

**Why round the skills and the target?** Problem choice then depends only on integers and the generator, so a 1-ulp
float difference between JS and Python (for example in `log10`) can't change which problem is chosen. Elo itself
stays in floats. Rounding the target moves it by at most 0.5 rating points, which players won't notice.

**Generation skills vs. rating:** `gen` starts as the player's per-skill ratings when the session starts (sent by the
client as `startSkills` with the session's first event) and moves forward only with that session's own rounds.
The **real** rating update is always applied to the server's current player row. The two match whenever play is
sequential. If two devices play at once, the problems are still verifiable and ratings stay correct, because Elo is
order-sensitive but each update is honest. The server checks `startSkills` loosely (each value within ±300 of the
server's value). Picking easier problems only earns tiny Elo gains, so a lie here gains nothing.

### 2.3 Times are integers, clamped the same way on both sides

Add this to the engine (TS and Python):

```ts
export const MIN_TIME_MS = 250;
export const normalizeTime = (ms: number) => Math.min(ROUND_LIMIT_MS, Math.max(MIN_TIME_MS, Math.round(ms)));
```

The client calls `normalizeTime` **before** `applyRound` and sends that exact integer. A timeout sends `choice: null`
with `timeMs: ROUND_LIMIT_MS`. Both sides then compute exactly the same Elo. On the backend, `rules.MIN_TIME_MS`
(currently 120) is replaced by the engine constant.

### 2.4 Outbox events

The outbox is stored in localStorage under `magnitude:outbox:v1`, as an ordered list. Each event is written **before**
the UI shows the result.

```ts
type OutboxEvent =
  | { kind: "practice"; sessionId: string; index: number; startSkills?: Record<Skill, number>; // index 0 only
      choice: Side | null; timeMs: number; at: number; localDate: string;
      // fingerprint + data to re-apply locally during reconcile (server recomputes, never trusts these)
      problemId: string; skill: Skill; problemRating: number; correct: boolean }
  | { kind: "daily"; date: string; index: number; choice: Side | null; timeMs: number; at: number;
      problemId: string; skill: Skill; problemRating: number; correct: boolean };
```

- **Idempotency key:** `(sessionId, index)` for practice and `(date, index)` for daily. The server acks duplicates
  without applying them again.
- `at` is the client's epoch ms. `localDate` is `dateKey(at)`.

### 2.5 Sync

- **When:** every 5 new events, when leaving `/duel`, on `visibilitychange → hidden`, on the `online` event,
  and on app start if the outbox isn't empty. Never more than one request in flight (`navigator.locks.request("magnitude-sync")`
  stops two tabs from flushing at the same moment; idempotency covers the rest).
- **Leaving the page:** use `fetch(url, { method: "POST", keepalive: true, headers: {Authorization…} })`.
  **Not** `navigator.sendBeacon`, which can't send the `Authorization` header. Keep keepalive bodies under 64 KB
  (about 150 events), and send the rest on the next visit.
- **Batch size:** at most 200 events per request.
- **Retry:** exponential backoff (1s, 2s, 4s … up to 60s) on network errors, 5xx and 429. Small UI indicator:
  "N unsynced" when the outbox has been non-empty for more than 30s.

### 2.6 Server replay, per sync request

All events in a request are processed in **one transaction**, with the player row locked `FOR UPDATE` once:

1. Practice event `(sessionId, index)`:
   - The session must exist, belong to this player and not be expired.
   - If `index < session.next_index`, it is a duplicate: ack and skip.
   - If `index > session.next_index`, reject with `gap` (the client lost an event; this should not happen).
   - If `index == 0`, check `startSkills` and store it as `session.gen_skills`.
   - `problem = session_problem(seed, index, session.gen_skills)`.
   - **Fingerprint check:** `problem.id == event.problemId` and `problem.rating == event.problemRating`. If either
     differs, reject with `mismatch`, mark the session `broken`, and log at ERROR (this means an engine parity bug).
   - `correct = choice == problem.answer`, `time = normalize_time(timeMs)`.
   - `service.apply_outcome(...)` on the player row (the existing function), and store the round with
     `session_id`, `round_index`, `at = event.at`.
   - `session.gen_skills = next_gen_skills(...)`, `session.next_index += 1`.
2. Daily event `(date, index)`: same as the existing `answer_daily` logic, but the problem comes from
   `daily_problem(date, index)` in-process (no problem service, no Redis), with the same fingerprint check.
   The 10th event writes `DailyResult`.
3. **Plausibility checks.** Failing one rejects the event; it doesn't fail the batch.
   - `at ≤ now + 60s` and `at ≥ session.issued_at − 60s`.
   - `localDate` within ±1 day of the UTC date of `at` (replaces "±1 day of today", so late syncs work).
   - Within a session, `sum(timeMs) ≤ (last at − first at) + timeMs(first) + 2s × rounds`, so reported think times
     can't add up to more time than actually passed.
4. Once a session event is rejected, every later event in **that session** is rejected with `session_broken`.
   Other sessions and daily events continue.
5. Commit, drop the `profile:{player}` cache, and return the response.

```jsonc
// POST /v1/sync → 200
{ "acked": [{"kind":"practice","sessionId":"…","index":7}, …],          // includes duplicates
  "rejected": [{"kind":"practice","sessionId":"…","index":8,"reason":"mismatch"}],
  "profile": { /* exactly the frontend Profile type, as GET /v1/profile */ } }
```

### 2.7 Reconcile on the client

When a sync response arrives:

1. Remove every acked **and** rejected event from the outbox. Rejected events are logged to the console and dropped;
   the server's view wins.
2. `local = response.profile`, then re-apply any events still in the outbox (ones added while the request was in
   flight) with `applyRound`, using their stored `skill`, `problemRating`, `correct`, `timeMs` and `at`.
3. Save the result. If a duel is open, update its profile ref. **Don't** change `gen` for the running session: it
   carries on from its own state.

Normally the server profile already matches the local one exactly, so the player never sees a change.

### 2.8 Dashboard loading

`GET /v1/profile` is stale-while-revalidate: render from `magnitude:profile:v1` straight away, fetch in the
background, then reconcile as in 2.7. The 30s Redis profile cache stays.

### 2.9 Remaining round trips

- **CORS preflight:** a JSON `POST` with `Authorization` triggers an `OPTIONS` request every time. Set `max_age=86400`
  on `CORSMiddleware` so the browser caches the preflight.
- **Region:** deploy the rating service in the same AWS region as the Neon project and the Upstash database
  (relevant to Phase 5).
- The problem service is no longer used during play (see step 6).

## 3. Data model changes: migration `0002_sessions`

```python
op.create_table(
    "sessions",
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
    sa.Column("seed", sa.BigInteger(), nullable=False),            # uint32 doesn't fit a signed int4
    sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("gen_skills", json_type, nullable=True),              # set by index 0
    sa.Column("next_index", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("time_sum_ms", sa.BigInteger(), nullable=False, server_default="0"),
    sa.Column("status", sa.String(8), nullable=False, server_default="open"),  # open | broken
)
op.create_index("ix_sessions_player", "sessions", ["player_id", "issued_at"])
op.add_column("players", sa.Column("imported", sa.Boolean(), nullable=False, server_default=sa.false()))  # see section 8
op.add_column("rounds", sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True))
op.add_column("rounds", sa.Column("round_index", sa.Integer(), nullable=True))
op.create_index("uq_rounds_session", "rounds", ["session_id", "round_index"], unique=True,
                postgresql_where=sa.text("session_id IS NOT NULL"))
```

Add matching ORM fields in `models.py`, including `sqlite_where` on the new index, the same way `uq_rounds_daily`
does it. `uq_rounds_daily` stays as it is and still blocks a daily problem being answered twice.

## 4. API changes (rating service)

| Endpoint | Change |
| --- | --- |
| `POST /v1/sessions` | **New.** Rate limited (30/min/player). Returns `{sessionId, seed, expiresAt}`. |
| `POST /v1/sync` | **New.** Body `{events: OutboxEvent[]}` (1–200). Returns `{acked, rejected, profile}`. Pydantic discriminated union on `kind`. |
| `GET /v1/profile` | Unchanged. |
| `POST /v1/players` | Unchanged. Optional one-time import, see section 8. |
| `POST /v1/rounds/next`, `/rounds/answer` | **Removed** in step 6, along with the `prob:{id}` Redis keys. |
| `GET/POST /v1/daily/{date}…` | **Removed** in step 6. The client builds the daily set itself, and answers go through `/sync`. The "already done today" state comes from `profile.daily`. |

## 5. Frontend changes

| File | Change |
| --- | --- |
| `lib/engine/session.ts` | Add `roundRng`, `sessionProblem`, `nextGenSkills`, `roundSkills`. |
| `lib/engine/elo.ts` | Add `MIN_TIME_MS`, `normalizeTime`. |
| `lib/api.ts` (new) | `fetch` wrapper: base URL from `NEXT_PUBLIC_API_URL`, bearer token, 10s timeout, typed errors (`offline`, `unauthorized`, `retryable`, `fatal`). |
| `lib/auth.ts` (new) | Token stored in `magnitude:token:v1`. If there is no token, call `POST /v1/players` once, deduplicating concurrent calls. A 401 → show "Account not found" (no silent re-signup, which would wipe progress). |
| `lib/sync.ts` (new) | Ticket pool, outbox, flush scheduler, reconcile. Exposes `useSyncStatus()` for the indicator. Everything goes through one module-level singleton. |
| `lib/profile.ts` | Stays the local cache. Add `replaceProfile(server, pending)` for reconcile. |
| `hooks/useDuel.ts` | Practice: on mount, take a ticket and set `gen = profile.skills`. `begin(i)` → `sessionProblem(seed, i, gen)`. `answer()` → `normalizeTime`, `applyRound`, **push the outbox event, then** update state, then `gen = nextGenSkills(...)`. Daily: same, with `dailyProblem`. Leaving the duel → `sync.flush({keepalive: true})`. |
| `components/home/Dashboard.tsx` | Kick off `sync.flush()` and the ticket refill on mount. Small "N unsynced / offline" pill. |
| `.env.local` | `NEXT_PUBLIC_API_URL=http://localhost:8000`, `NEXT_PUBLIC_SYNC=on`. |

With `NEXT_PUBLIC_SYNC=off`, `sync.ts` becomes a no-op and `useDuel` uses a locally made seed (`crypto.getRandomValues`).
The game stays playable without a backend.

## 6. Implementation steps

**Step 0: make the existing backend tests run.** They have never been run (see `backend/README.md`, "Status").
Install the dev requirements and get both pytest suites, the parity suite and the pure suite passing on `main`
before changing anything. Fix whatever they find in a separate commit.

**Step 1: engine (TS + Python), parity first.**
1. Add `roundRng`, `sessionProblem`, `nextGenSkills`, `roundSkills`, `MIN_TIME_MS` and `normalizeTime` to `lib/engine`.
2. Extend `scripts/generate-golden.ts` with:
   - `sessionProblems`: 5 seeds × 4 gen-skill sets × indexes 0–49.
   - `sessionReplays`: 6 scripted sessions (seed, startSkills, 60 `{choice, timeMs}` answers, mixing right, wrong,
     timeout, fast and slow) → the problem sequence plus the final `gen` and player rating after each round,
     starting from the given profile.
   - `normalizeTime` cases (including 0, 249.6, 250.4, 7999.5 and 9000).
3. `npm run golden`, then port to `magnitude_engine/session.py` and `elo.py` (use `js_round` and 32-bit masking).
4. Add parity tests. Problems must match with **`assertEqual`**; ratings with `assertAlmostEqual(places=9)`.
5. `npm run verify:engine` still passes.

Done when: `python -m unittest discover -s tests/parity` passes.

**Step 2: backend.**
1. Migration `0002_sessions` and the ORM fields.
2. `service.py`: `create_session`, `replay_practice(session, player, event)`, `replay_daily(...)`, plus the
   plausibility checks as pure functions in `rules.py` (tested in `test_pure.py`).
3. `routes.py`: `POST /v1/sessions`, `POST /v1/sync`. Set CORS `max_age=86400`.
4. Tests in `tests/test_sync.py`. The test client plays through the **Python engine**, the way the browser would.
   Cover:
   - happy path, with the server profile equal to a locally computed one;
   - a retried batch (no double counting);
   - an index gap;
   - a fingerprint mismatch that breaks the session but leaves other events alone;
   - an expired or foreign session;
   - impossible timing;
   - a late sync (`at` 3 days ago);
   - a full daily set through sync, and a duplicate daily answer;
   - two concurrent syncs for one player (both succeed, applied in order);
   - a batch over the limit (422);
   - rate limiting.

Done when: both pytest suites pass, `docker compose -f docker-compose.yml -f docker-compose.local.yml up` starts,
and `alembic upgrade head` applies 0002 against local Postgres.

**Step 3: client plumbing (behind the flag).** `lib/api.ts`, `lib/auth.ts`, `lib/sync.ts`, the `profile.ts`
changes, and the dashboard pill. `useDuel` is still unchanged.
Done when: the dashboard signs up, keeps 2 tickets in the pool, and shows the server profile. `npm run typecheck` passes.

**Step 4: switch `useDuel` over.** Practice and daily go through tickets and the outbox, as in section 5.
Done when: you can play with the backend running; with the backend stopped you can play from the ticket pool and the
pill shows unsynced rounds, which sync once it's back. The DevTools Network tab shows nothing during a round.

**Step 5: end-to-end parity script.** Add `scripts/e2e-sync.ts` (`npm run e2e:sync`). Against the local Docker stack
it signs up, plays 200 scripted rounds and 1 daily set through the real `lib/engine` and `lib/sync` code (with a
localStorage shim), then checks that `GET /v1/profile` matches the local profile according to the acceptance criteria.
Done when: this passes 10 times in a row with random seeds.

**Step 6: cleanup.**
- Remove `/v1/rounds/*`, `/v1/daily/*`, `Cache.put_problem` / `take_problem` / `*_daily`, `problems_client.py`,
  `problem_ttl_seconds` and `daily_cache_seconds`.
- Remove the `problem` service from Docker Compose and drop the `/readyz` check for it. Keep
  `services/problem` in the repo only if you want it as a practice microservice (it is no longer on any request path).
- Update `backend/README.md`, `README.md` (phase table) and `OVERVIEW.md`.

## 7. Risks and how they're handled

| Risk | Handling |
| --- | --- |
| Small float differences between JS and Python change which problem is generated | Generation uses rounded integer skills and target (2.2). The fingerprint check catches anything left and only breaks that one session. Golden vectors require exact problem equality. |
| Engine edited in one language only | Parity suite in CI (Phase 5). Any session mismatch is logged at ERROR. |
| Outbox lost (storage cleared) before sync | Sync at least every 5 rounds and on hide/leave, so the most that can be lost is a few rounds. |
| Two tabs or devices playing at once | `navigator.locks` within one browser. Across devices, independent sessions and per-event server-side Elo keep things correct; the problem choice for each session still verifies. |
| Fake timings | Floor of 250ms, sum-of-times check against wall-clock time (2.6). This is good enough for single player. A public leaderboard would need server-issued seeds every N rounds plus stricter checks. |
| Client can work out future problems from the seed | Not a meaningful exploit: the answer is visible on screen anyway. |
| Token lost | Same as Phase 3: the account is gone. No change in this phase. |

## 8. Decisions taken by default (change before starting if you disagree)

1. **Existing local progress** (from Phases 1–2) is imported **once** at sign-up: `POST /v1/players {import: Profile}` is
   accepted without verification, stored with `players.imported = true`, and never accepted again. The alternative
   is to start everyone fresh on the server.
2. **The problem service** is retired from the request path in step 6, not deleted from the repo.
3. **The daily set** is answered locally and synced. The server stays authoritative through the fingerprint and
   ordering checks.
4. **Sync cadence:** every 5 events. You can tune this; lower means less to lose, higher means fewer requests.

## 9. Implementation notes (what differs from the spec above, and what was verified)

**Verified.** Parity suite 11/11 (exact equality on 1,200 session problems and six 60-round replays); rating service 49
tests on SQLite plus 4 against real Postgres (including 6 simultaneous identical syncs, applied once); migrations 0001 and
0002 apply to Postgres and 0002 downgrades and re-applies; Docker images build and run; `npm run e2e:sync` 10/10;
`node scripts/e2e-browser.mjs` passes (sync on) and `--sync-off` passes; `npm run build` succeeds.

**Step 0 found** two bugs in tests, not in the app: the parity test read `golden.json` with the Windows default encoding,
and a daily-set test asserted `"answer" not in …`, which also matched the `answered` field. Both fixed.

**Differences from the spec**

- **Any rejected practice event breaks its session** (not only a fingerprint mismatch), because later rounds depend on it.
  Added reason `out_of_range`. Daily events are rejected individually.
- **Daily answers older than 7 days are rejected** (`implausible_time`), so a past date's set can't be replayed freely.
- **A session in use stays valid**: each accepted event extends `expires_at` by 7 days from the time of the sync.
- **`409` on a conflicting commit** is returned as retryable. It can only happen without row locks (SQLite); on
  Postgres the player-row lock serializes syncs. Because SQLite tests share one connection, they can't show concurrency,
  so that is tested against real Postgres (`tests/test_live.py`, skipped unless `LIVE_API_URL` is set).
- **Import (decision 1)** needs each history record to carry its `localDate`, computed in the browser. Days the last 200
  rounds don't cover get placeholder rows (`mode = 'imported'`) so the heat strip and day streak survive. Skills must
  include all four. A partial map had been accepted until a test caught it.
- **The client** keeps the outbox only in localStorage (read-modify-write each time, no in-memory copy) so two tabs can't
  diverge; a batch the server calls malformed (4xx other than 401) is moved to `magnitude:outbox-dead:v1` instead of
  blocking the queue; a 401 stops retrying and shows "Account not found"; an unused ticket is put back when a duel screen
  unmounts (React StrictMode mounts effects twice in development); a keepalive flush with nothing to send is skipped.
- **"Reset progress" is hidden when sync is on**, since the server holds the real profile and there is no server reset.
- **`.env.example`** is provided instead of creating `.env.local`: copy it to `.env.local` to turn sync on.
- **`scripts/e2e-browser.mjs`** is an addition (real Chrome over the DevTools Protocol); `npm run e2e:sync` is as specified.
- **Step 6** removed `/v1/rounds/*`, `/v1/daily/*`, the `prob:*` and `daily:*` Redis keys, `problems_client.py`, the related
  settings, and the problem service from Compose and `/readyz`. `services/problem` stays in the repo (decision 2).

**Not done / still open:** frame-time measurement of the answer path; an automated literal tab-close test; calibrating
difficulty from real play data (a Phase 4 goal in the roadmap, separate from the latency work); Phase 5 (deploy, CI).
