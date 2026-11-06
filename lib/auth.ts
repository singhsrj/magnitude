import { ApiError, apiFetch } from "./api";
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
