# Magnitude

Two expressions, one keypress: which is bigger? An Elo rating adapts the difficulty so you are always
at the edge of what you can do quickly. Designed in Figma ("Magnitude — UI/UX"), built phase by phase.

## Run it

```bash
npm install
npm run dev            # http://localhost:3000
npm run verify:engine  # engine sanity checks (Elo, generator, simulated players)
npm run golden         # regenerate the test vectors the Python engine is checked against
npm run typecheck
```

Controls: `←` / `→` answer, `Space` or `Enter` continues, `Esc` leaves.

## Phases

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, Figma design tokens in Tailwind, Geist fonts, primitives (KeyCap, StatPill, ExprCard) | done |
| 1 | Playable duel: problem generator, speed-adjusted Elo, keyboard play, local persistence | done |
| 2 | Home dashboard from Figma (rating chart, skills, daily set, last 20 rounds), playable daily set, wrong-answer shake, mobile layouts | done |
| 3 | Backend in `backend/` (FastAPI problem + rating services, Neon Postgres, Upstash Redis, Docker Compose); engine parity-tested against this app | built, see status in `backend/README.md` |
| 4 | Wire the UI to the API; server-side daily set; problem difficulty calibrated from real play | |
| 5 | AWS deploy (ECS + scheduled Lambda), CI, metrics | |

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
- Profile data lives in the browser (`localStorage`) until the backend exists, so progress doesn't sync across devices.

## Layout

```
app/                 routes (/, /duel, /duel/daily)
components/ui/       KeyCap, StatPill, Logo        (Figma components)
components/duel/     ExprCard, TimerBar, DuelScreen, DailySummary
components/home/     Dashboard, RatingCard + RatingChart, SkillsCard, DailyCard, RecentCard
hooks/useDuel.ts     duel state machine (practice and daily modes)
lib/engine/          pure game logic: elo, problems, session, stats, daily, dates, seeded rng (no React)
lib/format.ts        number and time formatting
lib/profile.ts       persistence (swapped for the API in Phase 4)
scripts/             engine verification, golden-vector generator
backend/             Phase 3: FastAPI services, Alembic migrations, Docker Compose (see backend/README.md)
```

The engine in `lib/engine` is deliberately framework-free so Phase 3 can port it to the Python service
and the two can be checked against each other.
