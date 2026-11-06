/**
 * End-to-end check of Phase 4 against a running backend (real Postgres + Redis):
 *
 *   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build     (in backend/)
 *   npm run e2e:sync
 *
 * It plays through the real `lib/engine` and `lib/sync` code (with a localStorage shim, no browser), the same
 * way `useDuel` does, then compares the server's profile with one computed locally and independently:
 *   - 200 practice rounds with background syncing in flight
 *   - a daily set
 *   - 20 rounds while "offline", then back online
 *   - 20 rounds whose sync response is lost after the server applied them (the retry must not double count)
 *
 * Sign-ups are limited per IP (10/hour by default): clear the local counters between runs with
 * `docker compose ... exec redis redis-cli flushall`.
 */
import assert from "node:assert/strict";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";
process.env.NEXT_PUBLIC_API_URL = API;
process.env.NEXT_PUBLIC_SYNC = "on";

// ---- minimal browser shims (the app code only touches these)
const store = new Map<string, string>();
const localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};
Object.assign(globalThis, {
  window: { localStorage, addEventListener() {}, removeEventListener() {} },
  document: { addEventListener() {}, visibilityState: "visible" },
});

// ---- network control: normal, offline, or "the server got it but the response never arrived"
type NetMode = "online" | "offline" | "drop-sync-response";
let net: NetMode = "online";
let syncPosts = 0;
const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
  if (net === "offline") throw new TypeError("fetch failed (simulated offline)");
  const url = String(input);
  const res = await realFetch(input, init);
  if (url.endsWith("/v1/sync")) {
    syncPosts += 1;
    if (net === "drop-sync-response") throw new TypeError("response lost (simulated)");
  }
  return res;
}) as typeof fetch;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const close = (a: number, b: number, what: string) => assert.ok(Math.abs(a - b) < 1e-9, `${what}: ${a} vs ${b}`);

async function main() {
  const E = await import("../lib/engine");
  const sync = await import("../lib/sync");
  const { apiFetch } = await import("../lib/api");
  const { getToken } = await import("../lib/auth");
  const { saveProfile } = await import("../lib/profile");
  type Profile = import("../lib/engine").Profile;
  type Skill = import("../lib/engine").Skill;

  try {
    const ready = await realFetch(`${API}/readyz`);
    assert.ok(ready.ok, `backend not ready: ${ready.status}`);
  } catch (err) {
    throw new Error(`can't reach ${API}. Start the stack first (see the header of this file). ${err}`);
  }

  // `pure` is computed independently here, only from the engine; `ui` is what the app would show: it is
  // replaced whenever a sync finishes (like `onProfile` in useDuel). They must agree at the end.
  let pure: Profile = E.newProfile();
  let ui: Profile = E.newProfile();
  sync.onProfile((p) => (ui = p));

  const ticket = await sync.acquireTicket();
  assert.ok(ticket, "got a session ticket");
  const session = { index: 0, gen: { ...ui.skills } as Record<Skill, number>, start: { ...ui.skills } as Record<Skill, number> };
  console.log(`session ${ticket.sessionId.slice(0, 8)} seed ${ticket.seed}`);

  // The server checks answers against wall-clock time, so play on a synthetic clock that ends "now": an hour of
  // real play can't be compressed, but rounds at the 250 ms floor fit ~300 rounds in the server's window.
  let clock = Date.now() - 58_000;
  let timeouts = 0;
  const answerPractice = (i: number) => {
    const problem = E.sessionProblem(ticket.seed, session.index, session.gen);
    const timeout = i % 60 === 59;
    const roll = (i * 2654435761) % 10; // deterministic mix of right and wrong
    const choice = timeout ? null : roll < 7 ? problem.answer : problem.answer === "left" ? "right" : "left";
    const timeMs = timeout ? E.ROUND_LIMIT_MS : E.normalizeTime(250 + ((i * 37) % 60));
    if (timeout) timeouts += 1;
    clock += timeMs + 10;
    const at = clock;
    const correct = choice !== null && choice === problem.answer;
    pure = E.applyRound(pure, problem, correct, timeMs, at).profile;
    ui = E.applyRound(ui, problem, correct, timeMs, at).profile;
    saveProfile(ui);
    sync.pushEvent({
      kind: "practice", sessionId: ticket.sessionId, index: session.index,
      ...(session.index === 0 ? { startSkills: session.start } : {}),
      localDate: E.dateKey(at), choice, timeMs, at, problemId: problem.id, skill: problem.skill, problemRating: problem.rating, correct,
    });
    session.gen = E.nextGenSkills(session.gen, problem, correct, timeMs);
    session.index += 1;
  };
  const playPractice = async (n: number, pauseMs = 5) => {
    for (let k = 0; k < n; k++) {
      answerPractice(session.index);
      if (pauseMs) await sleep(pauseMs); // lets background syncs run between rounds, like real play
    }
  };

  // ---- A: 200 practice rounds with syncs happening while we play
  await playPractice(200);
  await sync.flush();
  assert.equal(sync.getSyncStatus().pending, 0, "outbox drained after the first 200 rounds");
  assertSame(ui, pure, "UI profile after 200 rounds", close);
  console.log(`ok  200 practice rounds (${syncPosts} sync requests, ${timeouts} timeouts); UI profile == local profile`);

  // ---- B: a daily set
  const day = E.dateKey(clock);
  const dailyRounds: { correct: boolean; timeMs: number }[] = [];
  for (let i = 0; i < E.DAILY_LENGTH; i++) {
    const problem = E.dailyProblem(day, i);
    const choice = i === 3 ? (problem.answer === "left" ? "right" : "left") : problem.answer;
    const timeMs = E.normalizeTime(260 + i);
    clock += timeMs + 10;
    const correct = choice === problem.answer;
    pure = E.applyRound(pure, problem, correct, timeMs, clock).profile;
    ui = E.applyRound(ui, problem, correct, timeMs, clock).profile;
    dailyRounds.push({ correct, timeMs });
    sync.pushEvent({ kind: "daily", date: day, index: i, choice, timeMs, at: clock, problemId: problem.id, skill: problem.skill, problemRating: problem.rating, correct });
    await sleep(5);
  }
  const dailyResult = { correct: dailyRounds.filter((r) => r.correct).length, total: 10, timeMs: dailyRounds.reduce((s, r) => s + r.timeMs, 0) };
  pure = E.recordDaily(pure, day, dailyResult);
  ui = E.recordDaily(ui, day, dailyResult);
  await sync.flush();
  assertSame(ui, pure, "UI profile after the daily set", close);
  assert.deepEqual(ui.daily[day], dailyResult);
  console.log(`ok  daily set synced (${dailyResult.correct}/10)`);

  // ---- C: offline for 20 rounds, then back online
  net = "offline";
  const before = syncPosts;
  await playPractice(20);
  await sync.flush(); // fails quietly: nothing may be lost
  assert.equal(sync.getSyncStatus().pending, 20, "20 rounds wait in the outbox while offline");
  assert.equal(syncPosts, before, "nothing reached the server while offline");
  assert.ok(sync.getSyncStatus().offline, "status says offline");
  net = "online";
  await sync.flush();
  assert.equal(sync.getSyncStatus().pending, 0, "outbox drained once back online");
  assertSame(ui, pure, "UI profile after the offline rounds", close);
  console.log("ok  20 rounds played offline synced once the connection came back");

  // ---- D: the server applies a batch but the response is lost; the retry must not count it twice
  net = "drop-sync-response";
  await playPractice(20, 0);
  await sync.flush();
  assert.equal(sync.getSyncStatus().pending, 20, "client still holds the events (it never saw the ack)");
  net = "online";
  await sync.flush();
  assert.equal(sync.getSyncStatus().pending, 0, "retry succeeded");
  assertSame(ui, pure, "UI profile after the lost-response retry", close);
  console.log("ok  lost response: the retry was acknowledged as duplicates, nothing double counted");

  // ---- E: the server's own view (a fresh GET) matches the independent local computation
  const token = getToken();
  assert.ok(token);
  const server = await apiFetch<Profile>("/v1/profile", { token });
  assertSame(server, pure, "server profile vs local computation", close);
  assert.equal(server.rounds, 200 + 10 + 20 + 20);
  assert.equal(JSON.parse(store.get("magnitude:outbox:v1") ?? "[]").length, 0, "outbox is empty in storage");
  assert.equal(store.get("magnitude:outbox-dead:v1"), undefined, "nothing was dead-lettered");
  console.log(`ok  server profile matches: rating ${server.rating.toFixed(3)}, ${server.rounds} rounds, ${server.history.length} in history`);
  console.log("\nE2E PASSED");
  process.exit(0);
}

function assertSame(a: import("../lib/engine").Profile, b: import("../lib/engine").Profile, label: string, near: (x: number, y: number, w: string) => void) {
  near(a.rating, b.rating, `${label}: rating`);
  near(a.peak, b.peak, `${label}: peak`);
  for (const s of E_SKILLS) near(a.skills[s], b.skills[s], `${label}: skill ${s}`);
  assert.equal(a.streak, b.streak, `${label}: streak`);
  assert.equal(a.bestStreak, b.bestStreak, `${label}: bestStreak`);
  assert.equal(a.rounds, b.rounds, `${label}: rounds`);
  assert.equal(a.history.length, b.history.length, `${label}: history length`);
  a.history.forEach((h, i) => {
    const g = b.history[i];
    assert.deepEqual({ ...h, delta: 0 }, { ...g, delta: 0 }, `${label}: history[${i}]`);
    near(h.delta, g.delta, `${label}: history[${i}].delta`);
  });
  assert.deepEqual(a.days, b.days, `${label}: days`);
  assert.deepEqual(a.daily, b.daily, `${label}: daily`);
}
const E_SKILLS = ["multiplication", "percentages", "fractions", "powers"] as const;

main().catch((err) => {
  console.error("\nE2E FAILED:", err);
  process.exit(1);
});
