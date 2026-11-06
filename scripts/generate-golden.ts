/**
 * Writes golden test vectors from the TypeScript engine so the Python engine
 * (backend/packages/engine) can be checked against it: same seed, same output.
 * Run: npm run golden
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import {
  DAILY_LENGTH, ROUND_LIMIT_MS, SKILLS, dailyProblem, dailySeed, generateProblem, mulberry32,
  nextGenSkills, normalizeTime, pickSkill, roundRng, sessionProblem, targetProblemRating, updatePlayer, type Skill,
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

// ---- Phase 4: practice sessions -----------------------------------------------------------------------
const GEN_SETS: Record<Skill, number>[] = [
  { multiplication: 1200, percentages: 1200, fractions: 1200, powers: 1200 },
  { multiplication: 1500, percentages: 1350, fractions: 1100, powers: 1250 },
  { multiplication: 1000, percentages: 1900, fractions: 1450, powers: 1000 },
  { multiplication: 1234.5, percentages: 1187.49, fractions: 1301.5, powers: 999.51 }, // non-integer ratings
];
const SESSION_SEEDS = [1, 42, 2024, 4294967295, 3141592653];

const roundRngs = [0, 1, 7, 499].map((index) => ({
  seed: 2024, index, values: (() => { const r = roundRng(2024, index); return Array.from({ length: 12 }, () => r()); })(),
}));

const sessionProblems = SESSION_SEEDS.flatMap((seed) =>
  GEN_SETS.map((gen, g) => ({
    seed, gen, problems: Array.from({ length: 50 }, (_, index) => sessionProblem(seed, index, gen)), g,
  })),
);

// Scripted sessions: a separate rng decides right / wrong / timeout and a raw (float) think time per round.
const sessionReplays = [...SESSION_SEEDS, 99991].map((seed, n) => {
  const start = GEN_SETS[n % GEN_SETS.length];
  const script = mulberry32(seed + 17);
  let gen = start;
  let rating = 1200 + n * 40;
  let skills = { ...start };
  const rounds = [];
  for (let index = 0; index < 60; index++) {
    const problem = sessionProblem(seed, index, gen);
    const roll = script();
    const rawMs = [120, 249.6, 250.4, 640, 900, 2100, 3500, 5200, 7999.5, 9000][Math.floor(script() * 10)];
    const mode = roll < 0.65 ? "right" : roll < 0.85 ? "wrong" : "timeout";
    const choice = mode === "timeout" ? null : mode === "right" ? problem.answer : problem.answer === "left" ? "right" : "left";
    const timeMs = mode === "timeout" ? ROUND_LIMIT_MS : normalizeTime(rawMs);
    const correct = choice !== null && choice === problem.answer;
    const overall = updatePlayer(rating, problem.rating, correct, timeMs);
    const skill = updatePlayer(skills[problem.skill], problem.rating, correct, timeMs);
    rating = overall.next;
    skills = { ...skills, [problem.skill]: skill.next };
    gen = nextGenSkills(gen, problem, correct, timeMs);
    rounds.push({ index, rawMs, choice, timeMs, problemId: problem.id, skill: problem.skill, problemRating: problem.rating,
      answer: problem.answer, correct, rating, skills, gen });
  }
  return { seed, startSkills: start, startRating: 1200 + n * 40, rounds };
});

const normalizeCases = [-5, 0, 1, 249.4, 249.5, 249.6, 250, 250.4, 1000.5, 7999.4, 7999.5, 8000, 9000, 120000].map(
  (ms) => ({ ms, result: normalizeTime(ms) }),
);

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ rng, problems, sequences, daily, elo, targetRatings, picks, roundRngs, sessionProblems, sessionReplays, normalizeCases }, null, 1));
console.log(`wrote ${OUT}: ${problems.length} problems, ${sequences.length * 40} sequenced, ${daily.length * DAILY_LENGTH} daily, ${elo.length} elo, ${sessionProblems.length * 50} session problems, ${sessionReplays.length} replays`);
