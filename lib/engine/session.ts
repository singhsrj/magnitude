import { DEFAULT_RATING, updatePlayer } from "./elo";
import { dateKey } from "./dates";
import type { Rng } from "./rng";
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
