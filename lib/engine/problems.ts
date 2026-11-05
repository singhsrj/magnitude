import { Rng, pick, randInt } from "./rng";
import type { Expr, Problem, Side, Skill } from "./types";

const SUP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
};
const sup = (n: number) => String(n).split("").map((c) => SUP[c] ?? c).join("");

const SKILL_OFFSET: Record<Skill, number> = {
  multiplication: 0,
  percentages: -40,
  fractions: 30,
  powers: 60,
};

interface Candidate {
  left: Expr;
  right: Expr;
  /** Rough complexity of the arithmetic, ~log10 of the numbers involved */
  size: number;
}

/**
 * Difficulty on the Elo scale. Two things make a comparison hard:
 * big/awkward numbers (size) and the two values being close together (gap).
 */
export function difficulty(skill: Skill, size: number, left: number, right: number): number {
  const hi = Math.max(Math.abs(left), Math.abs(right));
  const gap = Math.abs(left - right) / hi;
  const closeness = Math.min(-Math.log10(Math.max(gap, 0.0005)) * 200, 700);
  return Math.round(600 + SKILL_OFFSET[skill] + size * 140 + closeness);
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

const A_TIERS: Array<[number, number]> = [[3, 19], [12, 99], [101, 499], [101, 999]];
const B_TIERS: Array<[number, number]> = [[3, 9], [12, 99], [12, 99], [101, 299]];

const make: Record<Skill, (rng: Rng) => Candidate> = {
  multiplication(rng) {
    const t = randInt(rng, 0, A_TIERS.length - 1);
    const a = randInt(rng, ...A_TIERS[t]);
    const b = randInt(rng, ...B_TIERS[t]);
    const v1 = a * b;
    const spread = Math.max(2, Math.round(a * 0.15));
    const jitter = pick(rng, [0, 1, 2, 3, 6, 12]);
    const c = Math.max(3, a + randInt(rng, -spread, spread));
    const d = Math.max(3, Math.round(v1 / c) + randInt(rng, -jitter, jitter));
    return {
      left: { text: `${a} × ${b}`, value: v1 },
      right: { text: `${c} × ${d}`, value: c * d },
      size: Math.log10(Math.max(v1, c * d)),
    };
  },

  percentages(rng) {
    // tier 0: round percents of round numbers; tier 2: awkward percents of awkward numbers
    const tier = randInt(rng, 0, 2);
    const pct = () => (tier === 2 ? randInt(rng, 1, 99) : randInt(rng, 1, 19) * 5);
    const base = () => (tier === 0 ? randInt(rng, 2, 40) * 10 : tier === 1 ? randInt(rng, 25, 999) : randInt(rng, 120, 1999));
    const x = pct();
    const n = base();
    const v1 = (x * n) / 100;
    let right: Expr;
    if (rng() < 0.5) {
      const off = pick(rng, [-0.2, -0.08, -0.03, -0.01, 0.01, 0.03, 0.08, 0.2]);
      const n2 = Math.max(1, Math.round(v1 * (1 + off)));
      right = { text: String(n2), value: n2 };
    } else {
      const y = pct();
      const m = base();
      right = { text: `${y}% of ${m}`, value: (y * m) / 100 };
    }
    return { left: { text: `${x}% of ${n}`, value: v1 }, right, size: Math.log10(n) + tier * 0.4 };
  },

  fractions(rng) {
    const t = randInt(rng, 0, 2);
    const maxDen = [12, 24, 60][t];
    const b = randInt(rng, 3, maxDen);
    const a = randInt(rng, 1, b - 1);
    const d = randInt(rng, 3, maxDen);
    const jit = pick(rng, [0, 1, 2]);
    const c = rng() < 0.7 ? clamp(Math.round((a / b) * d) + randInt(rng, -jit, jit), 1, d - 1) : randInt(rng, 1, d - 1);
    return {
      left: { text: `${a}/${b}`, value: a / b },
      right: { text: `${c}/${d}`, value: c / d },
      size: Math.log10(b * d) + t * 0.3,
    };
  },

  powers(rng) {
    const t = randInt(rng, 0, 2);
    const maxBase = [9, 12, 16][t];
    const maxExp = [5, 7, 9][t];
    const a = randInt(rng, 2, maxBase);
    const m = randInt(rng, 2, maxExp);
    const v1 = a ** m;
    const n = randInt(rng, 2, maxExp);
    const b = rng() < 0.7 ? Math.max(2, Math.round(v1 ** (1 / n)) + randInt(rng, -1, 1)) : randInt(rng, 2, maxBase);
    const v2 = b ** n;
    return {
      left: { text: `${a}${sup(m)}`, value: v1 },
      right: { text: `${b}${sup(n)}`, value: v2 },
      size: Math.log10(Math.max(v1, v2)) * 0.7,
    };
  },
};

export interface GenerateOptions {
  skill: Skill;
  targetRating: number;
  rng: Rng;
}

/**
 * Samples a batch of valid candidates and keeps the one whose difficulty is
 * closest to the target. No problem bank needed, and a seeded rng gives
 * reproducible sets (daily challenge, tests).
 */
export function generateProblem({ skill, targetRating, rng }: GenerateOptions): Problem {
  let best: (Candidate & { rating: number; dist: number }) | null = null;
  let valid = 0;
  for (let attempts = 0; attempts < 512 && valid < 64; attempts++) {
    const cand = make[skill](rng);
    const hi = Math.max(Math.abs(cand.left.value), Math.abs(cand.right.value));
    if (Math.abs(cand.left.value - cand.right.value) / hi < 0.0005) continue; // too close to call
    valid++;
    const rating = difficulty(skill, cand.size, cand.left.value, cand.right.value);
    const dist = Math.abs(rating - targetRating);
    if (!best || dist < best.dist) best = { ...cand, rating, dist };
  }
  if (!best) throw new Error(`Could not generate a ${skill} problem`);

  const swap = rng() < 0.5;
  const [left, right] = swap ? [best.right, best.left] : [best.left, best.right];
  const answer: Side = left.value > right.value ? "left" : "right";
  return {
    id: `${skill}-${Math.floor(rng() * 1e9).toString(36)}`,
    skill,
    left,
    right,
    rating: best.rating,
    answer,
  };
}
