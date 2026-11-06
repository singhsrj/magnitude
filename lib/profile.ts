import { migrateProfile, newProfile } from "./engine/session";
import type { Profile } from "./engine/types";
import { reconcileProfile } from "./reconcile";
import type { OutboxEvent } from "./syncTypes";

/**
 * The local copy of the profile: what the app renders and plays from, always, even offline.
 * With sync on, the server is the source of truth and this is a cache that `replaceProfile` keeps current.
 */
const KEY = "magnitude:profile:v1";

export function loadProfile(): Profile {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const migrated = migrateProfile(JSON.parse(raw));
      if (migrated) return migrated;
    }
  } catch {
    /* storage unavailable or corrupt: start fresh */
  }
  return newProfile();
}

export function saveProfile(profile: Profile): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(profile));
  } catch {
    /* private mode / quota: the game still works for this session */
  }
}

export function resetProfile(): Profile {
  const fresh = newProfile();
  saveProfile(fresh);
  return fresh;
}

/**
 * Adopts the server's profile (plus rounds it hasn't acknowledged yet) as the local one.
 * Returns the profile that was stored.
 */
export function replaceProfile(server: Profile, pending: readonly OutboxEvent[]): Profile {
  const next = reconcileProfile(server, pending);
  saveProfile(next);
  return next;
}
