/**
 * Browser-level check of Phase 4 with real Chrome (headless), driven over the DevTools Protocol. No dependencies.
 *
 *   (in backend/)  docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
 *   (in repo root) NEXT_PUBLIC_API_URL=http://localhost:8000 NEXT_PUBLIC_SYNC=on npx next dev -p 3000
 *   (in repo root) node scripts/e2e-browser.mjs
 *
 * Checks, in the real app:
 *   - the dashboard creates the account and keeps 2 session tickets in the pool
 *   - no request starts while a round is running (between "question shown" and the keypress)
 *   - rounds are sent in the background every 5 answers, and the server ends up with every round
 *   - 6 rounds played while offline show the pill and sync after the connection returns
 *
 * CHROME=<path to chrome.exe> overrides the browser. APP_URL / API_URL override the defaults.
 */
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";

const APP = process.env.APP_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000";
const CHROME =
  process.env.CHROME ??
  ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].find(existsSync);
assert.ok(CHROME, "no Chrome/Edge found; set CHROME=<path>");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9300 + Math.floor(Math.random() * 500);

// ---- launch and connect
const profileDir = mkdtempSync(join(tmpdir(), "magnitude-chrome-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profileDir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--window-size=1280,800", "about:blank"], { stdio: "ignore" });
const cleanup = () => { try { chrome.kill(); } catch { /* already gone */ } };
process.on("exit", cleanup);

let target;
for (let i = 0; i < 50 && !target; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" });
    target = await res.json();
  } catch { await sleep(200); }
}
assert.ok(target?.webSocketDebuggerUrl, "could not reach Chrome's debugging port");

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let nextId = 1;
const pending = new Map();
const requests = []; // { t, method, url } for everything sent to the API
const problems = []; // uncaught exceptions and console errors from the page
ws.onmessage = (msg) => {
  const data = JSON.parse(msg.data);
  if (data.id && pending.has(data.id)) {
    const { resolve, reject } = pending.get(data.id);
    pending.delete(data.id);
    data.error ? reject(new Error(JSON.stringify(data.error))) : resolve(data.result);
  } else if (data.method === "Runtime.exceptionThrown") {
    problems.push(`exception: ${data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text}`);
  } else if (data.method === "Runtime.consoleAPICalled" && ["error", "assert"].includes(data.params.type)) {
    problems.push(`console.${data.params.type}: ${data.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  } else if (data.method === "Network.requestWillBeSent" && data.params.request.url.startsWith(API)) {
    requests.push({ t: data.params.wallTime * 1000, method: data.params.request.method, url: data.params.request.url.replace(API, "") });
  }
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(`evaluate failed: ${expression}\n${JSON.stringify(r.exceptionDetails)}`);
  return r.result.value;
};
const keyLog = [];
const key = async (k, code, vk) => {
  keyLog.push({ k, t: Date.now() });
  const base = { key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk };
  await send("Input.dispatchKeyEvent", { type: "keyDown", ...base });
  await send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
};
const waitFor = async (what, fn, ms = 15000) => {
  const end = Date.now() + ms;
  let lastError = null;
  for (;;) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (err) {
      lastError = err; // e.g. document.body is null for a moment while a navigation is in progress
    }
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}${lastError ? ` (last error: ${String(lastError.message).slice(0, 160)})` : ""}`);
    await sleep(100);
  }
};
const status = () => evaluate(`document.querySelector('p[aria-live=polite]')?.textContent ?? ''`);
const ls = (k) => evaluate(`window.localStorage.getItem(${JSON.stringify(k)})`);
const outboxLen = async () => JSON.parse((await ls("magnitude:outbox:v1")) ?? "[]").length;
const serverProfile = async () => {
  const token = await ls("magnitude:token:v1");
  const res = await fetch(`${API}/v1/profile`, { headers: { Authorization: `Bearer ${token}` } });
  return res.json();
};


const rounds = [];
const play = async (n, label) => {
  for (let i = 0; i < n; i++) {
    await waitFor("question", async () => (await status()) === "Which is bigger?");
    const shownAt = Date.now();
    await sleep(350); // a real round lasts seconds; give any stray request time to show up
    const answeredAt = Date.now();
    const side = rounds.length % 2 === 0 ? ["ArrowLeft", 37] : ["ArrowRight", 39];
    await key(side[0], side[0], side[1]);
    await waitFor("result", async () => (await status()) !== "Which is bigger?");
    rounds.push({ shownAt, answeredAt });
    // The result screen: a person takes a moment here. The sync an answer triggers starts a few ms after it,
    // so it lands on this screen and never in the next question's window.
    await sleep(300);
    await key(" ", "Space", 32);
  }
  console.log(`    ${label}: played ${n} rounds`);
};

async function checkSyncOn() {
  // ---- 1) dashboard: account + tickets
  await send("Page.navigate", { url: `${APP}/` });
  await waitFor("account token", () => ls("magnitude:token:v1"));
  const tickets = await waitFor("2 tickets in the pool", async () => {
    const t = JSON.parse((await ls("magnitude:tickets:v1")) ?? "[]");
    return t.length >= 2 ? t : null;
  });
  console.log(`ok  dashboard created the account and holds ${tickets.length} session tickets`);

  // ---- 2) practice rounds: nothing sent while a round is running
  await send("Page.navigate", { url: `${APP}/duel` });
  await waitFor("first question", async () => (await status()) === "Which is bigger?");
  await play(12, "online");

  const duringRounds = requests
    .map((r) => ({ ...r, round: rounds.findIndex((x) => r.t > x.shownAt && r.t < x.answeredAt) }))
    .filter((r) => r.round !== -1)
    .map((r) => ({ method: r.method, url: r.url, round: r.round + 1, msAfterQuestionShown: Math.round(r.t - rounds[r.round].shownAt) }));
  if (duringRounds.length) {
    const t0 = keyLog[0].t;
    console.error("timeline (ms since first key):", JSON.stringify([
      ...keyLog.map((e) => ({ t: Math.round(e.t - t0), key: e.k })),
      ...requests.map((r) => ({ t: Math.round(r.t - t0), req: `${r.method} ${r.url}` })),
    ].sort((a, b) => a.t - b.t).filter((e) => e.t > 0)));
  }
  assert.deepEqual(duringRounds, [], `requests started while a round was running: ${JSON.stringify(duringRounds)}`);
  console.log("ok  no request started between a question appearing and the answer (12 rounds)");

  await waitFor("two background syncs", () => requests.filter((r) => r.method === "POST" && r.url === "/v1/sync").length >= 2);
  console.log(`ok  rounds were sent in the background (${requests.filter((r) => r.url === "/v1/sync").length} sync requests after 12 answers)`);

  // ---- 3) leaving the duel sends the rest; the server has every round
  await send("Page.navigate", { url: `${APP}/` });
  await waitFor("outbox drained", async () => (await outboxLen()) === 0);
  assert.equal((await serverProfile()).rounds, 12);
  console.log("ok  server has all 12 rounds; outbox is empty");

  // ---- 4) offline: 6 rounds, the pill, then back online
  await send("Page.navigate", { url: `${APP}/duel` });
  await waitFor("question", async () => (await status()) === "Which is bigger?");
  // Block only the API (not the dev server), which is what "the backend is unreachable" looks like to the app.
  await send("Network.setBlockedURLs", { urls: [`${API}/*`] });
  await play(6, "offline");
  assert.equal(await outboxLen(), 6, "6 rounds wait in the outbox");
  await send("Page.navigate", { url: `${APP}/` });
  const pill = await waitFor("the offline pill", () => evaluate(`document.querySelector('[role=status]')?.textContent ?? ''`), 10000);
  assert.match(pill, /Offline.*6 unsynced/);
  console.log(`ok  offline: 6 rounds held locally; the dashboard pill says "${pill}"`);
  await send("Network.setBlockedURLs", { urls: [] });
  await waitFor("outbox to drain after reconnecting", async () => (await outboxLen()) === 0, 30000);
  assert.equal((await serverProfile()).rounds, 18);
  console.log("ok  back online: the 6 offline rounds synced (server has 18)");

  // ---- 5) the daily set, through the real UI
  await send("Page.navigate", { url: `${APP}/duel/daily` });
  await waitFor("first daily question", async () => (await status()) === "Which is bigger?");
  await play(10, "daily set");
  // play() already pressed Space after the 10th result ("Space to see your score"), which opens the summary
  await waitFor("the daily summary", async () => /daily/i.test(await evaluate("document.body.innerText")));
  await send("Page.navigate", { url: `${APP}/` });
  await waitFor("outbox drained", async () => (await outboxLen()) === 0);
  const final = await serverProfile();
  const dailyDays = Object.keys(final.daily);
  assert.equal(final.rounds, 28, "12 + 6 + 10 rounds on the server");
  assert.equal(dailyDays.length, 1, "the daily result was recorded once");
  assert.equal(final.daily[dailyDays[0]].total, 10);
  console.log(`ok  daily set synced: ${final.daily[dailyDays[0]].correct}/10 recorded for ${dailyDays[0]}`);

  console.log("\nBROWSER E2E PASSED");
}

async function checkSyncOff() {
  // NEXT_PUBLIC_SYNC unset/off: the app must behave exactly as before Phase 4 and never touch a backend.
  await send("Page.navigate", { url: `${APP}/` });
  await waitFor("the dashboard", async () => /Start your first duel/i.test(await evaluate("document.body.innerText")));
  await send("Page.navigate", { url: `${APP}/duel` });
  await waitFor("first question", async () => (await status()) === "Which is bigger?");
  await play(6, "sync off");
  await send("Page.navigate", { url: `${APP}/` });
  await waitFor("the dashboard", async () => /Start duel/i.test(await evaluate("document.body.innerText")));
  assert.match(await evaluate("document.body.innerText"), /Reset progress/, "the local reset button is still there");
  assert.deepEqual(requests, [], `the app contacted the API with sync off: ${JSON.stringify(requests)}`);
  assert.equal(await ls("magnitude:token:v1"), null, "no account was created");
  assert.equal(await ls("magnitude:outbox:v1"), null, "no outbox");
  assert.equal(JSON.parse(await ls("magnitude:profile:v1")).rounds, 6, "progress is saved locally");
  console.log("ok  sync off: 6 rounds played and saved locally, no request to the API, no account");
  console.log("\nBROWSER E2E (sync off) PASSED");
}

try {
  await send("Network.enable");
  await send("Page.enable");
  await send("Runtime.enable");
  await (process.argv.includes("--sync-off") ? checkSyncOff() : checkSyncOn());
  process.exitCode = 0;
} catch (err) {
  console.error("\nBROWSER E2E FAILED:", err);
  try {
    console.error("page text:", JSON.stringify((await evaluate("document.body.innerText")).slice(0, 400)));
    console.error("localStorage keys:", await evaluate("Object.keys(window.localStorage).join(', ')"));
  } catch { /* page not reachable */ }
  if (problems.length) console.error("page problems:\n  " + problems.join("\n  "));
  process.exitCode = 1;
} finally {
  ws.close();
  cleanup();
}
