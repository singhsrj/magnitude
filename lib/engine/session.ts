import { DEFAULT_RATING, targetProblemRating, updatePlayer } from "./elo";
import { dateKey } from "./dates";
import { generateProblem } from "./problems";
import { mulberry32, type Rng } from "./rng";
import { SKILLS, type DailyResult, type Problem, type Profile, type Skill } from "./types";

const HISTORY_CAP = 200;

export function newProfile(): Profile {
  return {
    rating: DEFAULT_RATING,
    peak: DEFAULT_RATING,
    skills: { multiplication: DEFAULT_RATING, percentages: DEFAULT_RATING, fractions: DEFAULT_RATING, powers: DEFAULT_RATING },
    streak: 0,
    bestStreak: 0,
    rounds: 0,
    history: [],
    days: {},
    daily: {},
  };
}

/**
 * Validates data read from storage. Accepts older shapes (Phase 1 had no `days`/`daily`)
 * and fills the gaps; returns null if it isn't a usable profile.
 */
export function migrateProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== "object") return null;
  const p = raw as Partial<Profile>;
  const nums = [p.rating, p.peak, p.streak, p.rounds];
  if (nums.some((n) => typeof n !== "number" || !Number.isFinite(n))) return null;
  if (!Array.isArray(p.history) || !p.skills) return null;
  if (!SKILLS.every((s) => typeof p.skills![s] === "number")) return null;
  const base = newProfile();
  return {
    ...base,
    ...(p as Profile),
    bestStreak: typeof p.bestStreak === "number" ? p.bestStreak : p.streak!,
    days: p.days && typeof p.days === "object" ? p.days : {},
    daily: p.daily && typeof p.daily === "object" ? p.daily : {},
  };
}

export interface RoundOutcome {
  profile: Profile;
  /** Change to the overall rating this round (unrounded) */
  delta: number;
  /** Win probability the player had going in */
  expected: number;
  score: number;
}

/** Pure: returns the next profile; never mutates the input. */
export function applyRound(profile: Profile, problem: Problem, correct: boolean, timeMs: number, now = Date.now()): RoundOutcome {
  const overall = updatePlayer(profile.rating, problem.rating, correct, timeMs);
  const skill = updatePlayer(profile.skills[problem.skill], problem.rating, correct, timeMs);
  const streak = correct ? profile.streak + 1 : 0;
  const key = dateKey(now);
  const today = profile.days[key] ?? { rounds: 0, correct: 0 };
  const next: Profile = {
    rating: overall.next,
    peak: Math.max(profile.peak, overall.next),
    skills: { ...profile.skills, [problem.skill]: skill.next },
    streak,
    bestStreak: Math.max(profile.bestStreak, streak),
    rounds: profile.rounds + 1,
    history: [
      ...profile.history,
      { at: now, skill: problem.skill, correct, timeMs, delta: overall.delta, problemRating: problem.rating },
    ].slice(-HISTORY_CAP),
    days: { ...profile.days, [key]: { rounds: today.rounds + 1, correct: today.correct + (correct ? 1 : 0) } },
    daily: profile.daily,
  };
  return { profile: next, delta: overall.delta, expected: overall.expected, score: overall.score };
}

/** Stores a finished daily set. The first completion of a day is the one that counts. */
export function recordDaily(profile: Profile, key: string, result: DailyResult): Profile {
  if (profile.daily[key]) return profile;
  return { ...profile, daily: { ...profile.daily, [key]: result } };
}

/** Weaker skills come up more often, but every skill stays in rotation. */
export function pickSkill(rng: Rng, skills: Record<Skill, number>): Skill {
  const avg = SKILLS.reduce((sum, s) => sum + skills[s], 0) / SKILLS.length;
  const weights = SKILLS.map((s) => 1 + Math.min(2, Math.max(0, (avg - skills[s]) / 150)));
  let roll = rng() * weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < SKILLS.length; i++) {
    roll -= weights[i];
    if (roll <= 0) return SKILLS[i];
  }
  return SKILLS[SKILLS.length - 1];
}

// ---------------------------------------------------------------------------------------------------------
// Practice sessions (Phase 4). The server issues a seed; every problem is a pure function of
// (seed, round index, generation skills), so the server can replay a session the client played offline.
// Mirrored by backend/packages/engine/magnitude_engine/session.py. Change both, then `npm run golden`.
// ---------------------------------------------------------------------------------------------------------

/** A session ends after this many rounds; the next one starts with a fresh seed. */
export const SESSION_MAX_ROUNDS = 500;

/** One generator per round, so rounds are independent of each other (same idea as dailyProblem). */
export function roundRng(seed: number, index: number): Rng {
  return mulberry32(seed ^ Math.imul(index + 1, 0x9e3779b1));
}

/** Ratings as whole numbers: problem choice then depends only on integers, never on float noise. */
export function roundSkills(skills: Record<Skill, number>): Record<Skill, number> {
  return {
    multiplication: Math.round(skills.multiplication),
    percentages: Math.round(skills.percentages),
    fractions: Math.round(skills.fractions),
    powers: Math.round(skills.powers),
  };
}

/**
 * Problem `index` of a practice session. `gen` are the session's generation skills before this round
 * (they start as the player's skill ratings and roll forward with `nextGenSkills`).
 */
export function sessionProblem(seed: number, index: number, gen: Record<Skill, number>): Problem {
  const rng = roundRng(seed, index);
  const rounded = roundSkills(gen);
  const skill = pickSkill(rng, rounded);
  const targetRating = Math.round(targetProblemRating(rounded[skill]));
  return generateProblem({ skill, targetRating, rng });
}

/** Generation skills after a round. Floats are kept; they are only rounded when a problem is picked. */
export function nextGenSkills(
  gen: Record<Skill, number>,
  problem: Pick<Problem, "skill" | "rating">,
  correct: boolean,
  timeMs: number,
): Record<Skill, number> {
  return { ...gen, [problem.skill]: updatePlayer(gen[problem.skill], problem.rating, correct, timeMs).next };
}
