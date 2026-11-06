"use client";

/**
 * Phase 4: play locally, sync in the background.
 *
 * - Tickets: the server issues `{sessionId, seed}` ahead of time; a session plays from its seed with no network.
 * - Outbox: every answer is appended (in localStorage, before the UI shows the result) and sent in batches.
 *   The server replays each batch with the Python engine and answers with the authoritative profile.
 * - Reconcile: local profile = server profile + rounds the server hasn't acknowledged yet.
 *
 * Nothing here is awaited on the answer path. All state lives in localStorage (read-modify-write on every
 * change), so two tabs can't diverge. With sync off (no API URL) every function is a cheap no-op.
 */
import { useSyncExternalStore } from "react";
import { ApiError, SYNC_ENABLED, apiFetch } from "./api";
import { authToken, authTokenNow } from "./auth";
import { migrateProfile, type Profile } from "./engine";
import { replaceProfile } from "./profile";
import { eventKey, type OutboxEvent, type SyncResponse, type Ticket } from "./syncTypes";

export { SYNC_ENABLED };

const OUTBOX_KEY = "magnitude:outbox:v1";
const DEAD_KEY = "magnitude:outbox-dead:v1";
const TICKETS_KEY = "magnitude:tickets:v1";

const FLUSH_EVERY = 5; // events
const BATCH_MAX = 200; // the server's limit per request
const KEEPALIVE_MAX = 100; // keepalive bodies must stay under 64 KB
const TICKET_POOL = 2;
const TICKET_MIN_LIFE_MS = 60 * 60 * 1000; // a ticket about to expire isn't worth starting a session with
const DEAD_MAX = 500;

// ------------------------------------------------------------------------------------------ storage
function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or private mode: the game keeps working, but unsynced rounds are at risk */
  }
}

const readOutbox = () => read<OutboxEvent[]>(OUTBOX_KEY, []);

// ------------------------------------------------------------------------------------------ status
export interface SyncStatus {
  enabled: boolean;
  /** Rounds played but not yet acknowledged by the server */
  pending: number;
  /** When the outbox last went from empty to non-empty (ms), for the "N unsynced" hint */
  unsyncedSince: number | null;
  syncing: boolean;
  /** The last request failed because there is no connection */
  offline: boolean;
  /** The server doesn't recognise our token. Progress here is not being saved. */
  accountLost: boolean;
  /** Unspent session tickets in the pool */
  tickets: number;
  lastError: string | null;
}

const INITIAL: SyncStatus = {
  enabled: SYNC_ENABLED, pending: 0, unsyncedSince: null, syncing: false, offline: false, accountLost: false, tickets: 0, lastError: null,
};
let status: SyncStatus = INITIAL;
const statusListeners = new Set<() => void>();

function setStatus(patch: Partial<SyncStatus>): void {
  const next = { ...status, ...patch };
  if ((Object.keys(next) as (keyof SyncStatus)[]).every((k) => next[k] === status[k])) return;
  status = next;
  statusListeners.forEach((l) => l());
}

function refreshCounts(): void {
  const pending = readOutbox().length;
  setStatus({
    pending,
    tickets: freshTickets().length,
    unsyncedSince: pending === 0 ? null : (status.unsyncedSince ?? Date.now()),
  });
}

/** Current status outside React (scripts, tests). */
export function getSyncStatus(): SyncStatus {
  return status;
}

export function useSyncStatus(): SyncStatus {
  return useSyncExternalStore(
    (l) => {
      statusListeners.add(l);
      return () => statusListeners.delete(l);
    },
    () => status,
    () => INITIAL,
  );
}

// ------------------------------------------------------------------------------------------ profile updates
const profileListeners = new Set<(p: Profile) => void>();

/** Called whenever a sync replaced the local profile. Returns an unsubscribe function. */
export function onProfile(listener: (p: Profile) => void): () => void {
  profileListeners.add(listener);
  return () => profileListeners.delete(listener);
}

/** Shows a profile that didn't come from a sync (after an account switch or sign-out). */
export function publishProfile(p: Profile): void {
  profileListeners.forEach((l) => l(p));
}

function adoptServerProfile(raw: unknown): void {
  const server = migrateProfile(raw);
  if (!server) {
    console.error("[sync] the server sent a profile this app can't read", raw);
    return;
  }
  const next = replaceProfile(server, readOutbox());
  profileListeners.forEach((l) => l(next));
}

// ------------------------------------------------------------------------------------------ tickets
function freshTickets(): Ticket[] {
  const now = Date.now();
  return read<Ticket[]>(TICKETS_KEY, []).filter((t) => t.expiresAt - now > TICKET_MIN_LIFE_MS);
}

/** Takes an unused ticket from the pool, or null. Tops the pool up in the background. */
export function takeTicket(): Ticket | null {
  const pool = freshTickets();
  const ticket = pool.shift() ?? null;
  write(TICKETS_KEY, pool);
  refreshCounts();
  if (ticket) void refillTickets();
  return ticket;
}

/** Puts back a ticket that was taken but never used (the screen went away before the session began). */
export function returnTicket(ticket: Ticket): void {
  if (!SYNC_ENABLED || !Number.isFinite(ticket.expiresAt)) return; // local tickets (sync off) aren't pooled
  write(TICKETS_KEY, [ticket, ...freshTickets()]);
  refreshCounts();
}

let refilling: Promise<void> | null = null;

/** Keeps TICKET_POOL tickets ready so starting a duel never waits on the network. */
export function refillTickets(): Promise<void> {
  if (!SYNC_ENABLED || typeof window === "undefined") return Promise.resolve();
  refilling ??= (async () => {
    try {
      const token = await authToken();
      while (freshTickets().length < TICKET_POOL) {
        const ticket = await apiFetch<Ticket>("/v1/sessions", { method: "POST", token });
        write(TICKETS_KEY, [...freshTickets(), ticket]);
        refreshCounts();
      }
      setStatus({ offline: false });
    } catch (err) {
      noteError(err);
    } finally {
      refilling = null;
    }
  })();
  return refilling;
}

function localTicket(): Ticket {
  const seed = crypto.getRandomValues(new Uint32Array(1))[0];
  return { sessionId: crypto.randomUUID(), seed, expiresAt: Number.POSITIVE_INFINITY };
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });

/**
 * A ticket to start a practice session with. Instant when one is in the pool (the normal case). Otherwise waits
 * for the network, retrying. With sync off a local seed is used and nothing is ever sent.
 * Resolves null if `signal` aborts first.
 */
export async function acquireTicket(signal?: AbortSignal): Promise<Ticket | null> {
  if (!SYNC_ENABLED) return localTicket();
  while (!signal?.aborted) {
    const ticket = takeTicket();
    if (ticket) return ticket;
    await refillTickets();
    const after = takeTicket();
    if (after) return after;
    if (status.accountLost) await sleep(5000, signal);
    else await sleep(1500, signal);
  }
  return null;
}

// ------------------------------------------------------------------------------------------ outbox
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let retryAttempt = 0;

/** Records an answer. Synchronous and local; sending happens later, in the background. */
export function pushEvent(event: OutboxEvent): void {
  if (!SYNC_ENABLED) return;
  write(OUTBOX_KEY, [...readOutbox(), event]);
  refreshCounts();
  if (status.pending >= FLUSH_EVERY && retryTimer === null) void flush();
}

function removeFromOutbox(keys: Set<string>): void {
  write(OUTBOX_KEY, readOutbox().filter((e) => !keys.has(eventKey(e))));
}

function deadLetter(events: OutboxEvent[], why: string): void {
  console.error(`[sync] dropping ${events.length} event(s) the server will never accept: ${why}`, events);
  write(DEAD_KEY, [...read<OutboxEvent[]>(DEAD_KEY, []), ...events].slice(-DEAD_MAX));
}

function noteError(err: unknown): void {
  const e = err instanceof ApiError ? err : new ApiError("retryable", String(err));
  setStatus({
    offline: e.kind === "offline",
    accountLost: e.kind === "unauthorized" ? true : status.accountLost,
    lastError: e.message,
  });
}

function scheduleRetry(): void {
  if (retryTimer !== null) return;
  retryAttempt += 1;
  const delay = Math.min(60_000, 1000 * 2 ** (retryAttempt - 1));
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void flush();
  }, delay);
}

let inFlight: Promise<void> | null = null;
let rerun = false;

/**
 * Sends the outbox, or just refreshes the profile when it is empty. One request at a time per tab (and one
 * per browser, via a Web Lock). `keepalive` is for page hide/close: it fires immediately and may outlive the page.
 */
export function flush({ keepalive = false }: { keepalive?: boolean } = {}): Promise<void> {
  if (!SYNC_ENABLED || typeof window === "undefined" || status.accountLost) return Promise.resolve();
  if (keepalive) return run(true);
  if (inFlight) {
    // The running pass may have read the outbox before the newest answers landed. Callers expect "what's
    // waiting now has been tried", so follow up once it ends (stops when empty, or a retry is scheduled).
    rerun = true;
    return inFlight.then(() => (readOutbox().length > 0 && retryTimer === null ? flush() : undefined));
  }
  inFlight = (async () => {
    try {
      await withLock(() => run(false));
    } finally {
      inFlight = null;
      if (rerun) {
        rerun = false;
        if (readOutbox().length >= FLUSH_EVERY && retryTimer === null) void flush();
      }
    }
  })();
  return inFlight;
}

async function withLock(fn: () => Promise<void>): Promise<void> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks) await locks.request("magnitude-sync", fn);
  else await fn();
}

async function run(keepalive: boolean): Promise<void> {
  setStatus({ syncing: true });
  try {
    const token = keepalive ? authTokenNow() : await authToken();
    if (!token) return;
    if (keepalive && readOutbox().length === 0) return; // leaving a screen with nothing to send
    const limit = keepalive ? KEEPALIVE_MAX : BATCH_MAX;

    if (readOutbox().length === 0) {
      adoptServerProfile(await apiFetch<unknown>("/v1/profile", { token }));
      succeed();
      return;
    }
    for (;;) {
      const batch = readOutbox().slice(0, limit);
      if (batch.length === 0) break;
      let res: SyncResponse;
      try {
        res = await apiFetch<SyncResponse>("/v1/sync", { method: "POST", body: { events: batch }, token, keepalive });
      } catch (err) {
        if (err instanceof ApiError && err.kind === "fatal") {
          deadLetter(batch, err.message); // a batch the server calls malformed would otherwise block everything behind it
          removeFromOutbox(new Set(batch.map(eventKey)));
          refreshCounts();
          continue;
        }
        throw err;
      }
      const done = new Set([...res.acked, ...res.rejected].map(eventKey));
      if (res.rejected.length) console.warn("[sync] the server rejected rounds; its view wins:", res.rejected);
      removeFromOutbox(done);
      adoptServerProfile(res.profile);
      refreshCounts();
      succeed();
      if (keepalive || batch.length < limit) break;
    }
  } catch (err) {
    noteError(err);
    if (!(err instanceof ApiError) || err.kind !== "unauthorized") scheduleRetry();
  } finally {
    setStatus({ syncing: false });
  }
}

function succeed(): void {
  retryAttempt = 0;
  setStatus({ offline: false, lastError: null });
}

// ------------------------------------------------------------------------------------------ lifecycle
let started = false;

/** Forgets everything this device holds for the previous identity: outbox, tickets, retry state. */
export function resetSyncState(): void {
  write(OUTBOX_KEY, []);
  write(DEAD_KEY, []);
  write(TICKETS_KEY, []);
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  retryAttempt = 0;
  setStatus({ pending: 0, tickets: 0, unsyncedSince: null, offline: false, accountLost: false, lastError: null });
}

/** Installs the background triggers (idempotent): tab hidden or closing, connection back, leftovers from last visit. */
export function startSync(): void {
  if (!SYNC_ENABLED || started || typeof window === "undefined") return;
  started = true;
  refreshCounts();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && readOutbox().length > 0) void flush({ keepalive: true });
  });
  window.addEventListener("pagehide", () => {
    if (readOutbox().length > 0) void flush({ keepalive: true });
  });
  window.addEventListener("online", () => {
    retryAttempt = 0;
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    void flush();
    void refillTickets();
  });
  void flush(); // anything left from the last visit, or just a fresh profile
  void refillTickets();
}
