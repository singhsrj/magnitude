"use client";

import { useEffect, useState } from "react";
import { useSyncStatus } from "@/lib/sync";

const STALE_AFTER_MS = 30_000;

/** Says nothing while syncing works. Appears only when rounds have been waiting a while, or can't be saved. */
export function SyncPill() {
  const s = useSyncStatus();
  const [, tick] = useState(0);

  // re-evaluate "waiting for more than 30 s" while rounds are pending
  useEffect(() => {
    if (!s.enabled || s.pending === 0) return;
    const id = window.setInterval(() => tick((n) => n + 1), 5000);
    return () => window.clearInterval(id);
  }, [s.enabled, s.pending]);

  if (!s.enabled) return null;

  const waiting = s.pending > 0 && s.unsyncedSince !== null && Date.now() - s.unsyncedSince > STALE_AFTER_MS;
  let text: string | null = null;
  let tone = "text-ink-tertiary";
  if (s.accountLost) {
    text = "Account not found · progress isn’t being saved";
    tone = "text-wrong";
  } else if (s.offline && s.pending > 0) {
    text = `Offline · ${s.pending} unsynced`;
  } else if (waiting) {
    text = `${s.pending} unsynced`;
  }
  if (!text) return null;

  return (
    <span role="status" className={`text-sm ${tone}`}>
      {text}
    </span>
  );
}
