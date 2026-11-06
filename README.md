# Magnitude

Two expressions, one keypress: which is bigger? An Elo rating adapts the difficulty so you are always
at the edge of what you can do quickly. Designed in Figma ("Magnitude — UI/UX"), built phase by phase.

## Run it

```bash
npm install
npm run dev            # http://localhost:3000
npm run verify:engine  # engine sanity checks (Elo, generator, sessions, reconcile, simulated players)
npm run golden         # regenerate the test vectors the Python engine is checked against
npm run typecheck
npm run e2e:sync       # play 250 rounds through the real sync code against a running backend (see below)
```

**With the backend (Phase 4):** copy `.env.example` to `.env.local`, start the backend
(`cd backend && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build`), then `npm run dev`.
Progress is then stored and verified on the server. Without `.env.local` the app runs entirely in the browser, as before.
Browser-level check in real Chrome: `node scripts/e2e-browser.mjs` (header of the file says what it needs).

**Deploying:** backend on Render, frontend on Vercel (or Netlify). See `DEPLOY.md`.

Controls: `←` / `→` answer, `Space` or `Enter` continues, `Esc` leaves.

## Phases

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, Figma design tokens in Tailwind, Geist fonts, primitives (KeyCap, StatPill, ExprCard) | done |
| 1 | Playable duel: problem generator, speed-adjusted Elo, keyboard play, local persistence | done |
| 2 | Home dashboard from Figma (rating chart, skills, daily set, last 20 rounds), playable daily set, wrong-answer shake, mobile layouts | done |
| 3 | Backend in `backend/` (FastAPI, Neon Postgres, Upstash Redis, Docker Compose); engine parity-tested against this app | done |
| 4 | Play locally from a server-issued seed, sync in the background, server replays and verifies (`PHASE_4.md`) | done; difficulty calibration from real play is still open |
| 5 | Deploy: backend on Render (`render.yaml`), frontend on Vercel or Netlify (`DEPLOY.md`); then CI and metrics | config ready, first deploy is manual |

## How the rating works

- Each round scores 0 to 1: wrong or timed out is 0, a slow correct answer 0.70, a fast one 1.00.
- Expected score is standard Elo: `1 / (1 + 10^((problem - player) / 400))`, K = 24.
- Problems are generated near a target difficulty so you "win" about 70% of the time
  (`targetProblemRating`). Difficulty comes from number size and how close the two values are.
- Each skill (multiplication, percentages, fractions, powers) has its own rating; weaker skills appear more often.

## Phase 2 notes

- **Dashboard (`/`)**: the rating chart is rebuilt from the round history (`ratingSeries`), so nothing extra is stored.
  "This week" sums the last 7 days of rating changes. "Weakest" only appears after 12 rounds and a 40+ point gap.
- **Daily set (`/duel/daily`)**: 10 problems seeded from the local date, on a fixed difficulty ramp, so it is the same on
  every device (Phase 4 serves it from the backend instead). Rating changes during the set count like practice rounds.
  The first completion each day is the one recorded; a finished day shows its score and a "Done" button.
- **Heat strip**: rounds played per local day over the last 14 days. The day streak counts consecutive days with
  at least one round; not having played yet today doesn't break it. (The "Streak" pill in the duel is correct answers in a row.)
- **Profile storage** gained `days` and `daily`. Phase 1 profiles are migrated automatically (`migrateProfile`).
- **Wrong answers**: the chosen card shakes once (off when the OS asks for reduced motion) and the correct card is revealed.
- **Mobile**: cards stack under 768px, the dashboard collapses to one column under 1024px.

### Known limits (to fix in Phase 3/4)

- The generator reaches roughly 900 to 1600 for percentages and fractions, 900 to 1800 for powers and
  multiplication. Above that, problems get easier than the target.
- Because correct answers always score at least 0.70, ratings settle a little below true ability and accuracy
  runs nearer 80% than 70%. Phase 4 calibrates this with real play data.
- The daily set's top difficulty lands around 1500, not the 1650 target, because the percentage and fraction
  generators top out near 1600 (see above).
- With sync off, profile data lives in the browser (`localStorage`) and doesn't follow you across devices. With sync on
  the server holds it (anonymous account per device; lose the token and the account is gone).

## Layout

```
app/                 routes: / (landing), /home (dashboard), /duel, /duel/daily, /sign-in, /sign-up (Clerk)
components/ui/       KeyCap, StatPill, Logo        (Figma components)
components/duel/     ExprCard, TimerBar, DuelScreen, DailySummary
components/landing/  landing page pieces: HeroDuel, AuthControls (Clerk), AuthShell
components/home/     Dashboard, RatingCard + RatingChart, SkillsCard, DailyCard, RecentCard
hooks/useDuel.ts     duel state machine (practice and daily modes)
lib/engine/          pure game logic: elo, problems, session, stats, daily, dates, seeded rng (no React)
lib/format.ts        number and time formatting
lib/profile.ts       local copy of the profile (a cache when sync is on)
lib/api.ts, auth.ts  backend access; the anonymous device token and the Clerk session token (Phase 4)
lib/account.ts       links a signed-in Clerk account to this device's progress; components/AccountSync.tsx drives it
lib/sync.ts          session tickets, outbox, background sync (Phase 4); lib/reconcile.ts is its pure core
scripts/             engine verification, golden-vector generator
render.yaml          Render Blueprint for the backend; vercel.json for the frontend (DEPLOY.md)
backend/             FastAPI rating service, Alembic migrations, Docker Compose (see backend/README.md)
```

The engine in `lib/engine` is deliberately framework-free so Phase 3 can port it to the Python service
and the two can be checked against each other.
