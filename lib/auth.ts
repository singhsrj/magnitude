import { ApiError, SYNC_ENABLED, apiFetch } from "./api";
import { loadProfile } from "./profile";
import { profileToImport } from "./reconcile";

const KEY = "magnitude:token:v1";

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function setToken(token: string): void {
  try {
    window.localStorage.setItem(KEY, token);
  } catch {
    throw new ApiError("fatal", "can't store the account token (is storage blocked?)");
  }
}

let inFlight: Promise<string> | null = null;

/**
 * The account token, creating the account on first use. Concurrent callers share one sign-up, and so do
 * two tabs (a Web Lock), so a device never ends up with two accounts. A token the server later rejects is
 * NOT replaced silently: that would start a new empty account and hide the old progress.
 */
export function ensureToken(): Promise<string> {
  const existing = getToken();
  if (existing) return Promise.resolve(existing);
  inFlight ??= withSignupLock(async () => {
    const again = getToken(); // another tab may have finished while we waited for the lock
    if (again) return again;
    const local = loadProfile();
    // Progress made before Phase 4 moves to the server once, as part of creating the account.
    const body = local.rounds > 0 ? { import: profileToImport(local) } : undefined;
    const created = await apiFetch<{ playerId: string; token: string }>("/v1/players", { method: "POST", body });
    setToken(created.token);
    return created.token;
  }).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function withSignupLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  return locks ? await locks.request("magnitude-signup", fn) : await fn();
}

// ------------------------------------------------------------------------------------------ Clerk account
/** True when this build has Clerk (a publishable key was set at build time). */
export const CLERK_ENABLED = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

declare global {
  interface Window {
    Clerk?: { session?: { getToken(): Promise<string | null> } | null };
  }
}

/**
 * Two ways to authenticate, one player behind each:
 * - device token (anonymous): created on first use, kept in localStorage;
 * - account: while signed in, Clerk's short-lived session token (about a minute) is the bearer token.
 * Clerk session tokens can't be awaited while a page is closing, so a recent one is cached for that case.
 */
let accountMode = false;
let cached: { token: string; at: number } | null = null;
let refreshTimer: ReturnType<typeof setInterval> | null = null;
const CACHE_MS = 50_000;

export function isAccountMode(): boolean {
  return accountMode;
}

export function setAccountMode(on: boolean): void {
  accountMode = on;
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
  cached = null;
  if (on && typeof window !== "undefined") {
    void freshClerkToken();
    refreshTimer = setInterval(() => void freshClerkToken(), 45_000);
  }
}

/** A valid Clerk session token (Clerk refreshes it itself when it is about to expire), or null. */
export async function freshClerkToken(): Promise<string | null> {
  try {
    const token = (await window.Clerk?.session?.getToken()) ?? null;
    if (token) cached = { token, at: Date.now() };
    return token;
  } catch {
    return null;
  }
}

// Until we know whether the visitor is signed in, requests wait: otherwise a signed-in visitor on a new device would
// first create a throwaway anonymous player. The wait is skipped without Clerk, and gives up after a few seconds
// (Clerk blocked or slow) so play is never held hostage.
let releaseGate: () => void = () => {};
let gate: Promise<void> | null = CLERK_ENABLED && SYNC_ENABLED ? makeGate(6000) : null;

function makeGate(timeoutMs: number): Promise<void> {
  return new Promise<void>((resolve) => {
    releaseGate = resolve;
    setTimeout(resolve, timeoutMs);
  });
}

/** Holds requests while the account is being linked or switched. Returns the function that lets them go. */
export function holdAuthGate(): () => void {
  if (!CLERK_ENABLED || !SYNC_ENABLED) return () => {};
  const previous = releaseGate;
  gate = makeGate(15_000);
  const mine = releaseGate;
  return () => {
    mine();
    previous();
  };
}

/** The bearer token for a request that can wait. */
export async function authToken(): Promise<string> {
  if (gate) await gate;
  if (accountMode) {
    const token = await freshClerkToken();
    if (token) return token;
    throw new ApiError("offline", "the sign-in token isn't available yet");
  }
  return ensureToken();
}

/** The bearer token right now, for a page that is closing (no waiting): null if there is none to send. */
export function authTokenNow(): string | null {
  if (accountMode) return cached && Date.now() - cached.at < CACHE_MS ? cached.token : null;
  return getToken();
}

export function clearDeviceToken(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: nothing to clear */
  }
}
