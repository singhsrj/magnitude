import { addDays, dateKey } from "./dates";
import { SKILLS, type Profile, type RoundRecord, type Skill } from "./types";

const DAY_MS = 86_400_000;

/**
 * Rating after each of the last `maxRounds` rounds, plus the rating before the first one.
 * Reconstructed backwards from the current rating, so nothing extra needs storing.
 */
export function ratingSeries(profile: Profile, maxRounds = 60): number[] {
  const h = profile.history.slice(-maxRounds);
  const series = new Array<number>(h.length + 1);
  let r = profile.rating;
  series[h.length] = r;
  for (let i = h.length - 1; i >= 0; i--) {
    r -= h[i].delta;
    series[i] = r;
  }
  return series;
}

export function weekDelta(profile: Profile, now = Date.now()): { delta: number; rounds: number } {
  const recent = profile.history.filter((r) => r.at >= now - 7 * DAY_MS);
  return { delta: recent.reduce((s, r) => s + r.delta, 0), rounds: recent.length };
}

/** Consecutive days with at least one round. Today not played yet doesn't break the streak. */
export function dayStreak(profile: Profile, today = dateKey()): number {
  let key = (profile.days[today]?.rounds ?? 0) > 0 ? today : addDays(today, -1);
  let streak = 0;
  while ((profile.days[key]?.rounds ?? 0) > 0) {
    streak++;
    key = addDays(key, -1);
  }
  return streak;
}

export function recentRounds(profile: Profile, n = 20): RoundRecord[] {
  return profile.history.slice(-n);
}

/** 0 = nothing played, otherwise 0.3 to 1 scaling with rounds played that day. */
export function dayIntensity(profile: Profile, key: string): number {
  const rounds = profile.days[key]?.rounds ?? 0;
  return rounds === 0 ? 0 : 0.3 + 0.7 * Math.min(1, rounds / 20);
}

/** Only flags a weakest skill once there's enough data and a real gap. */
export function weakestSkill(profile: Profile): Skill | null {
  if (profile.rounds < 12) return null;
  const sorted = [...SKILLS].sort((a, b) => profile.skills[a] - profile.skills[b]);
  const gap = profile.skills[sorted[sorted.length - 1]] - profile.skills[sorted[0]];
  return gap >= 40 ? sorted[0] : null;
}
