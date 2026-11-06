"use client";

/**
 * Joins the signed-in Clerk account to this device's progress, and undoes that when the person signs out.
 *
 * What happens on sign-in (POST /v1/players/link, authenticated with the Clerk session token):
 * - linked / created: this device's player now belongs to the account. Nothing local changes.
 * - existing: the account already has progress on the server (from another device). If this browser holds progress
 *   of its own, the person is asked before it is replaced by the account's; if they decline, they stay anonymous.
 * - 409 (the device's anonymous player belongs to a different account, e.g. a shared computer): this device's
 *   local data is dropped and the account gets a fresh player.
 */
import { ApiError, apiFetch } from "./api";
import { clearDeviceToken, freshClerkToken, getToken, holdAuthGate, setAccountMode } from "./auth";
import { loadProfile, resetProfile } from "./profile";
import { profileToImport } from "./reconcile";
import { flush, getSyncStatus, publishProfile, resetSyncState } from "./sync";

const LINKED_KEY = "magnitude:linked-user:v1";

function linkedUser(): string | null {
  try {
    return window.localStorage.getItem(LINKED_KEY);
  } catch {
    return null;
  }
}
function setLinkedUser(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(LINKED_KEY, id);
    else window.localStorage.removeItem(LINKED_KEY);
  } catch {
    /* storage blocked: the worst case is one extra confirmation prompt next visit */
  }
}

type LinkStatus = "linked" | "created" | "existing";

/** Forget this device's progress and identity (it belonged to somebody else, or the account chose to replace it). */
function wipeDevice(): void {
  resetSyncState();
  clearDeviceToken();
  publishProfile(resetProfile());
}

let declined: string | null = null;

/** Returns true when the device now acts as the account. */
export async function connectAccount(userId: string): Promise<boolean> {
  if (declined === userId) return false;
  const release = holdAuthGate(); // no request may run on the old identity while this decides
  try {
    const clerkToken = await freshClerkToken();
    if (!clerkToken) return false;

    const local = loadProfile();
    const anon = getToken();
    const post = (body: unknown) =>
      apiFetch<{ playerId: string; status: LinkStatus }>("/v1/players/link", { method: "POST", token: clerkToken, body });

    let res: { playerId: string; status: LinkStatus };
    try {
      res = await post({
        ...(anon ? { anonymousToken: anon } : {}),
        // Pre-sync progress on a device that never had an account moves over once, with the account's new player.
        ...(!anon && local.rounds > 0 ? { import: profileToImport(local) } : {}),
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && /device_account_linked_elsewhere/.test(err.message)) {
        wipeDevice();
        res = await post({});
      } else {
        throw err;
      }
    }

    if (res.status === "existing" && linkedUser() !== userId) {
      const hasLocal = local.rounds > 0 || getSyncStatus().pending > 0;
      if (hasLocal && !window.confirm(
        "This account already has progress saved online.\n\nUse it on this device? The progress stored only in this browser will be discarded.",
      )) {
        declined = userId;
        setAccountMode(false);
        return false;
      }
      wipeDevice(); // the account's progress replaces whatever this browser had
    }

    setLinkedUser(userId);
    setAccountMode(true);
    void flush(); // pulls the account's profile (or sends what was waiting)
    return true;
  } catch (err) {
    console.error("[account] couldn't link the signed-in account; staying on this device's own progress", err);
    setAccountMode(false);
    return false;
  } finally {
    release();
  }
}

/** The person signed out: this device goes back to a clean anonymous state (their progress stays in their account). */
export function leaveAccount(): void {
  declined = null;
  setAccountMode(false);
  setLinkedUser(null);
  wipeDevice();
}
