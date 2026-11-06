/**
 * Sanity checks for the game engine. Run: npm run verify:engine
 * Not a test framework on purpose; Phase 3 moves the heavy logic to the backend with real tests.
 */
import assert from "node:assert/strict";
import {
  DAILY_LENGTH, SKILLS, addDays, applyRound, dailyProblem, dayIntensity, dayStreak, expectedScore,
  MIN_TIME_MS, ROUND_LIMIT_MS, SESSION_MAX_ROUNDS, dateKey, generateProblem, lastDays, migrateProfile, mulberry32,
  newProfile, nextGenSkills, normalizeTime, outcomeScore, pickSkill, ratingSeries, recordDaily, roundRng,
  sessionProblem, targetProblemRating, updatePlayer, weakestSkill, weekDelta,
  type Skill,
} from "../lib/engine";
import { profileToImport, reconcileProfile } from "../lib/reconcile";
import type { OutboxEvent } from "../lib/syncTypes";

// 1) Elo basics
{
  assert.ok(Math.abs(expectedScore(1500, 1500) - 0.5) < 1e-9, "equal ratings -> 0.5");
  assert.ok(expectedScore(1700, 1500) > 0.7, "stronger player expected to win more");
  assert.equal(outcomeScore(false, 500), 0);
  assert.equal(outcomeScore(true, 100), 1);
  assert.ok(Math.abs(outcomeScore(true, 60000) - 0.7) < 1e-9);
  const t = targetProblemRating(1500);
  assert.ok(Math.abs(expectedScore(1500, t) - 0.7) < 1e-9, "target rating gives 70% expected score");
  assert.ok(updatePlayer(1500, t, true, 700).delta > 0, "fast correct answer gains");
  assert.ok(updatePlayer(1500, t, false, 700).delta < 0, "wrong answer loses");
  console.log("ok  elo basics");
}

// 2) Problems are valid, never ties, answer matches values
for (const skill of SKILLS) {
  const rng = mulberry32(42);
  for (let i = 0; i < 500; i++) {
    const p = generateProblem({ skill, targetRating: 900 + (i % 12) * 100, rng });
    assert.notEqual(p.left.value, p.right.value, `${skill}: tie generated`);
    assert.equal(p.answer, p.left.value > p.right.value ? "left" : "right");
    assert.ok(p.left.text.length > 0 && p.right.text.length > 0);
  }
}
console.log("ok  problems valid (2000 generated)");

// 3) Determinism: same seed, same problem
{
  const a = generateProblem({ skill: "multiplication", targetRating: 1200, rng: mulberry32(7) });
  const b = generateProblem({ skill: "multiplication", targetRating: 1200, rng: mulberry32(7) });
  assert.deepEqual(a, b);
  console.log("ok  seeded generation is deterministic");
}

// 4) Difficulty targeting: how close does the generator get to the requested rating?
for (const skill of SKILLS) {
  const rng = mulberry32(1);
  const errs: number[] = [];
  for (const target of [900, 1100, 1300, 1500]) {
    for (let i = 0; i < 100; i++) errs.push(Math.abs(generateProblem({ skill, targetRating: target, rng }).rating - target));
  }
  const mean = errs.reduce((a, b) => a + b, 0) / errs.length;
  console.log(`    ${skill.padEnd(15)} mean |rating - target| = ${mean.toFixed(1)}`);
  assert.ok(mean < 50, `${skill}: difficulty targeting too loose for 900-1500 (${mean.toFixed(1)})`);
}
console.log("ok  difficulty targeting");

// 5) Simulated player: rating should climb from 1200 toward the player's true ability and stabilise
function simulate(ability: number, rounds: number, seed: number) {
  const rng = mulberry32(seed);
  let profile = newProfile();
  const tail: number[] = [];
  let correctCount = 0;
  for (let i = 0; i < rounds; i++) {
    const skill: Skill = pickSkill(rng, profile.skills);
    const problem = generateProblem({ skill, targetRating: targetProblemRating(profile.skills[skill]), rng });
    const pWin = 1 / (1 + Math.pow(10, (problem.rating - ability) / 400));
    const correct = rng() < pWin;
    const timeMs = 900 + rng() * 4500;
    profile = applyRound(profile, problem, correct, timeMs, i).profile;
    if (i >= rounds - 300) { tail.push(profile.rating); if (correct) correctCount++; }
  }
  const mean = tail.reduce((a, b) => a + b, 0) / tail.length;
  return { mean, accuracy: correctCount / tail.length, profile };
}
for (const ability of [1400, 1700]) {
  const { mean, accuracy } = simulate(ability, 3000, 99);
  console.log(`    ability ${ability}: settled rating ~${mean.toFixed(0)}, accuracy ${(accuracy * 100).toFixed(0)}%`);
  assert.ok(mean > ability - 250 && mean < ability + 250, `rating did not settle near ability ${ability}`);
}
console.log("ok  simulated players converge");

// 6) applyRound is pure
{
  const p = newProfile();
  const snapshot = JSON.stringify(p);
  const problem = generateProblem({ skill: "fractions", targetRating: 1100, rng: mulberry32(3) });
  const out = applyRound(p, problem, true, 1000);
  assert.equal(JSON.stringify(p), snapshot, "input profile mutated");
  assert.equal(out.profile.rounds, 1);
  assert.equal(out.profile.streak, 1);
  console.log("ok  applyRound is pure");
}

// ---- Phase 2 additions ----

// 7) Rating series reconstructs the real history
{
  const rng = mulberry32(5);
  let profile = newProfile();
  const seen: number[] = [profile.rating];
  for (let i = 0; i < 40; i++) {
    const skill = pickSkill(rng, profile.skills);
    const problem = generateProblem({ skill, targetRating: targetProblemRating(profile.skills[skill]), rng });
    profile = applyRound(profile, problem, rng() < 0.7, 1500, 1_700_000_000_000 + i * 60_000).profile;
    seen.push(profile.rating);
  }
  const series = ratingSeries(profile, 60);
  assert.equal(series.length, 41);
  series.forEach((v, i) => assert.ok(Math.abs(v - seen[i]) < 1e-6, `series[${i}] mismatch`));
  const last10 = ratingSeries(profile, 10);
  assert.equal(last10.length, 11);
  assert.ok(Math.abs(last10[10] - profile.rating) < 1e-9);
  console.log("ok  rating series matches replayed history");
}

// 8) Day streak, heat intensity, week delta
{
  const today = "2026-10-28";
  const p = newProfile();
  p.days = { "2026-10-28": { rounds: 5, correct: 4 }, "2026-10-27": { rounds: 12, correct: 9 }, "2026-10-26": { rounds: 1, correct: 1 }, "2026-10-24": { rounds: 9, correct: 9 } };
  assert.equal(dayStreak(p, today), 3, "streak counts consecutive days ending today");
  p.days["2026-10-28"] = { rounds: 0, correct: 0 };
  assert.equal(dayStreak(p, today), 2, "unplayed today keeps yesterday's streak alive");
  assert.equal(dayStreak(newProfile(), today), 0);
  assert.equal(dayIntensity(p, "2026-10-25"), 0);
  assert.ok(dayIntensity(p, "2026-10-26") >= 0.3 && dayIntensity(p, "2026-10-27") > dayIntensity(p, "2026-10-26"));
  assert.equal(lastDays(14, today).length, 14);
  assert.equal(lastDays(14, today)[13], today);
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
  const now = 1_700_000_000_000;
  const q = newProfile();
  q.history = [
    { at: now - 10 * 86_400_000, skill: "powers", correct: true, timeMs: 1, delta: 50, problemRating: 1 },
    { at: now - 2 * 86_400_000, skill: "powers", correct: true, timeMs: 1, delta: 8, problemRating: 1 },
    { at: now - 1000, skill: "powers", correct: false, timeMs: 1, delta: -3, problemRating: 1 },
  ];
  const wd = weekDelta(q, now);
  assert.equal(wd.rounds, 2);
  assert.equal(wd.delta, 5);
  console.log("ok  streak, heat strip and week delta");
}

// 9) Weakest skill needs data and a real gap
{
  const p = newProfile();
  assert.equal(weakestSkill(p), null);
  p.rounds = 30;
  p.skills.powers = 1100;
  assert.equal(weakestSkill(p), "powers");
  p.skills.powers = 1190;
  assert.equal(weakestSkill(p), null, "gap too small to call out");
  console.log("ok  weakest skill");
}

// 10) Daily set: deterministic, ramps up, fixed length, differs by day
{
  const a = Array.from({ length: DAILY_LENGTH }, (_, i) => dailyProblem("2026-10-28", i));
  const b = Array.from({ length: DAILY_LENGTH }, (_, i) => dailyProblem("2026-10-28", i));
  const c = Array.from({ length: DAILY_LENGTH }, (_, i) => dailyProblem("2026-10-29", i));
  assert.deepEqual(a, b, "same date -> same set");
  assert.notDeepEqual(a.map((p) => p.id), c.map((p) => p.id), "different date -> different set");
  const first3 = a.slice(0, 3).reduce((s, p) => s + p.rating, 0) / 3;
  const last3 = a.slice(-3).reduce((s, p) => s + p.rating, 0) / 3;
  assert.ok(last3 > first3 + 300, `daily set should ramp (${first3.toFixed(0)} -> ${last3.toFixed(0)})`);
  assert.equal(new Set(a.map((p) => p.skill)).size, 4, "all four skills appear");
  console.log(`ok  daily set deterministic, ramps ${first3.toFixed(0)} -> ${last3.toFixed(0)}`);
}

// 11) Migration + recordDaily
{
  const v1 = { rating: 1300, peak: 1350, streak: 2, bestStreak: 5, rounds: 40, skills: { multiplication: 1300, percentages: 1250, fractions: 1280, powers: 1210 }, history: [] };
  const m = migrateProfile(v1);
  assert.ok(m && Object.keys(m.days).length === 0 && Object.keys(m.daily).length === 0);
  assert.equal(migrateProfile({ rating: "x" }), null);
  assert.equal(migrateProfile(null), null);
  const p1 = recordDaily(newProfile(), "2026-10-28", { correct: 8, total: 10, timeMs: 12000 });
  const p2 = recordDaily(p1, "2026-10-28", { correct: 1, total: 10, timeMs: 1 });
  assert.equal(p2.daily["2026-10-28"].correct, 8, "first completion wins");
  console.log("ok  migration and recordDaily");
}

// 12) Phase 4: sessions are reproducible, and the engine's session/time helpers behave
{
  const gen = { multiplication: 1200, percentages: 1300, fractions: 1100, powers: 1250 };
  assert.deepEqual(sessionProblem(7, 3, gen), sessionProblem(7, 3, gen), "same seed + index + skills -> same problem");
  assert.notEqual(sessionProblem(7, 3, gen).id, sessionProblem(8, 3, gen).id, "different seed -> different problem");
  assert.notEqual(sessionProblem(7, 3, gen).id, sessionProblem(7, 4, gen).id, "different index -> different problem");
  // a round's problem doesn't depend on how many numbers earlier rounds drew
  assert.deepEqual(roundRng(9, 5)(), roundRng(9, 5)());
  // float noise in the skills can't change the problem (they are rounded first)
  assert.deepEqual(sessionProblem(7, 3, gen), sessionProblem(7, 3, { ...gen, multiplication: 1200.2, powers: 1249.6 }));
  assert.equal(normalizeTime(0), MIN_TIME_MS);
  assert.equal(normalizeTime(249.6), 250);
  assert.equal(normalizeTime(99999), ROUND_LIMIT_MS);
  assert.equal(normalizeTime(1234.5), 1235);
  const p = sessionProblem(7, 0, gen);
  const next = nextGenSkills(gen, p, true, 600);
  assert.ok(next[p.skill] > gen[p.skill] || p.rating < gen[p.skill], "gen skill rolls forward");
  assert.equal(SESSION_MAX_ROUNDS, 500);
  console.log("ok  session problems are reproducible");
}

// 13) Phase 4: reconcile = server profile + rounds the server hasn't acknowledged
{
  const event = (i: number, correct: boolean, at: number): OutboxEvent => ({
    kind: "practice", sessionId: "s", index: i, choice: correct ? "left" : "right", timeMs: 900, at, localDate: dateKey(at),
    problemId: `p${i}`, skill: SKILLS[i % 4], problemRating: 1230 + i, correct,
  });
  const t0 = new Date(2026, 10, 5, 10, 0, 0).getTime();
  const events = Array.from({ length: 8 }, (_, i) => event(i, i % 3 !== 0, t0 + i * 4000));

  // "what the app already shows": all 8 applied locally
  let local = newProfile();
  for (const e of events) local = applyRound(local, { skill: e.skill, rating: e.problemRating } as never, e.correct, e.timeMs, e.at).profile;
  // "what the server holds": the first 5 applied. The last 3 are still pending.
  let server = newProfile();
  for (const e of events.slice(0, 5)) server = applyRound(server, { skill: e.skill, rating: e.problemRating } as never, e.correct, e.timeMs, e.at).profile;

  const merged = reconcileProfile(server, events.slice(5));
  assert.deepEqual(merged, local, "server + pending equals what the player already sees");
  assert.deepEqual(reconcileProfile(local, []), local, "nothing pending: the server profile is adopted as is");
  assert.equal(server.rounds, 5, "reconcile never mutates its input");

  // a complete daily set that is still unsynced is shown as done
  const daily: OutboxEvent[] = Array.from({ length: DAILY_LENGTH }, (_, i) => ({
    kind: "daily", date: "2026-11-05", index: i, choice: "left", timeMs: 1000, at: t0 + i * 3000,
    problemId: `d${i}`, skill: SKILLS[i % 4], problemRating: 1100 + 50 * i, correct: i !== 2,
  }));
  const withDaily = reconcileProfile(newProfile(), daily);
  assert.deepEqual(withDaily.daily["2026-11-05"], { correct: 9, total: 10, timeMs: 10000 });
  assert.equal(withDaily.rounds, 10);
  assert.equal(reconcileProfile(newProfile(), daily.slice(0, 6)).daily["2026-11-05"], undefined, "a partial set isn't reported as done");
  console.log("ok  reconcile");
}

// 14) Phase 4: the one-time import payload
{
  let p = newProfile();
  const t0 = new Date(2026, 10, 5, 23, 30).getTime();
  for (let i = 0; i < 230; i++) {
    p = applyRound(p, { skill: SKILLS[i % 4], rating: 1200 + (i % 50) } as never, i % 4 !== 0, 1000 + i, t0 + i * 60_000).profile;
  }
  const out = profileToImport(p);
  assert.equal(out.history.length, 200, "history is capped at what the server accepts");
  assert.equal(out.history[0].localDate, dateKey(out.history[0].at), "carries the player's own calendar day");
  assert.equal(out.rounds, 230);
  assert.deepEqual(out.skills, p.skills);
  assert.ok(Object.keys(out.days).length >= 2, "the run crossed midnight, so two days are reported");
  console.log("ok  import payload");
}
