import { migrateProfile, newProfile } from "./engine/session";
import type { Profile } from "./engine/types";

/**
 * Persistence: the browser's localStorage for now.
 * Phase 4 swaps this for the rating service API; keep the Profile shape the same.
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
