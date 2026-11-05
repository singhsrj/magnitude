/**
 * Writes golden test vectors from the TypeScript engine so the Python engine
 * (backend/packages/engine) can be checked against it: same seed, same output.
 * Run: npm run golden
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import {
  DAILY_LENGTH, SKILLS, dailyProblem, dailySeed, generateProblem, mulberry32,
  pickSkill, targetProblemRating, updatePlayer, type Skill,
} from "../lib/engine";

const OUT = "backend/tests/parity/golden.json";

const rng = [0, 1, 42, 99, 123456789, 2147483648, 4294967295].map((seed) => {
  const r = mulberry32(seed);
  return { seed, values: Array.from({ length: 24 }, () => r()) };
});

const targets = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900];
const problems = [];
for (const skill of SKILLS) {
  for (let seed = 1; seed <= 60; seed++) {
    const target = targets[seed % targets.length];
    problems.push({ skill, seed: seed * 7919, target, problem: generateProblem({ skill, targetRating: target, rng: mulberry32(seed * 7919) }) });
  }
}

// One rng consumed across many problems: catches any drift in how many numbers each step draws.
const sequences = SKILLS.map((skill) => {
  const r = mulberry32(2024);
  return {
    skill,
    seed: 2024,
    targets: Array.from({ length: 40 }, (_, i) => targets[i % targets.length]),
    problems: Array.from({ length: 40 }, (_, i) => generateProblem({ skill, targetRating: targets[i % targets.length], rng: r })),
  };
});

const dates = ["2026-10-28", "2026-10-29", "2026-01-01", "2027-02-28", "2026-12-31"];
const daily = dates.map((date) => ({
  date,
  seed: dailySeed(date),
  problems: Array.from({ length: DAILY_LENGTH }, (_, i) => dailyProblem(date, i)),
}));

const elo = [];
for (const player of [900, 1200, 1480, 1750]) {
  for (const problem of [800, 1053, 1300, 1600, 2000]) {
    for (const [correct, timeMs] of [[true, 300], [true, 800], [true, 3000], [true, 6000], [true, 8000], [false, 1500]] as const) {
      elo.push({ player, problem, correct, timeMs, result: updatePlayer(player, problem, correct, timeMs) });
    }
  }
}
const targetRatings = [1000, 1200, 1500, 1800].map((player) => ({ player, target: targetProblemRating(player) }));

const skillSets: Record<Skill, number>[] = [
  { multiplication: 1200, percentages: 1200, fractions: 1200, powers: 1200 },
  { multiplication: 1500, percentages: 1350, fractions: 1100, powers: 1250 },
  { multiplication: 1000, percentages: 1900, fractions: 1450, powers: 1000 },
];
const picks = skillSets.map((skills, i) => {
  const r = mulberry32(31 + i);
  return { skills, seed: 31 + i, picks: Array.from({ length: 30 }, () => pickSkill(r, skills)) };
});

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ rng, problems, sequences, daily, elo, targetRatings, picks }, null, 1));
console.log(`wrote ${OUT}: ${problems.length} problems, ${sequences.length * 40} sequenced, ${daily.length * DAILY_LENGTH} daily, ${elo.length} elo`);
