import { generateProblem } from "./problems";
import { mulberry32 } from "./rng";
import { SKILLS, type Problem } from "./types";

export const DAILY_LENGTH = 10;

/** Fixed difficulty ramp: the daily set doesn't adapt, so it is the same on every device. */
const TARGETS = [1000, 1050, 1100, 1200, 1250, 1300, 1400, 1450, 1550, 1650];

/** FNV-1a hash of the date key. */
export function dailySeed(key: string): number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Problem `index` (0-based) of the daily set for `key`. Deterministic. */
export function dailyProblem(key: string, index: number): Problem {
  const seed = dailySeed(key);
  return generateProblem({
    skill: SKILLS[(seed + index) % SKILLS.length],
    targetRating: TARGETS[index],
    rng: mulberry32(seed ^ Math.imul(index + 1, 0x9e3779b1)),
  });
}
