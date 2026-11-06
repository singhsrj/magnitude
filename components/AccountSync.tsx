"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef } from "react";
import { SYNC_ENABLED } from "@/lib/api";
import { CLERK_ENABLED, holdAuthGate } from "@/lib/auth";
import { connectAccount, leaveAccount } from "@/lib/account";

/**
 * Renders nothing. Keeps the sync layer's identity in step with Clerk: signed in -> the account's player,
 * signed out -> a clean anonymous device. Mounted once, in the root layout.
 */
export function AccountSync() {
  if (!CLERK_ENABLED || !SYNC_ENABLED) return null;
  return <Bridge />;
}

function Bridge() {
  const { isLoaded, isSignedIn, userId } = useAuth();
  const wasSignedIn = useRef(false);
  const releaseInitialGate = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    (async () => {
      if (isSignedIn && userId) {
        wasSignedIn.current = true;
        await connectAccount(userId);
      } else if (wasSignedIn.current) {
        wasSignedIn.current = false;
        leaveAccount();
      }
      if (!cancelled) releaseInitialGate.current?.();
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, userId]);

  // Requests wait for the first answer to "who is this?" (see authToken); it ends when the effect above has run.
  useEffect(() => {
    releaseInitialGate.current = holdAuthGate();
    return () => releaseInitialGate.current?.();
  }, []);

  return null;
}
