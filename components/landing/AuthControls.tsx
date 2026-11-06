import { Show, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { Suspense } from "react";

const ghost =
  "inline-flex h-10 items-center whitespace-nowrap rounded-control px-3 sm:px-4 text-sm font-medium text-ink-secondary hover:text-ink-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const solid =
  "inline-flex h-10 items-center whitespace-nowrap rounded-control bg-accent px-3 sm:px-4 text-sm font-semibold text-ink-onAccent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** Sign in / sign up for visitors, dashboard link and the account menu for signed-in players. */
export function AuthControls({ dashboardLink = true }: { dashboardLink?: boolean }) {
  return (
    <Suspense fallback={<div className="h-10 w-40" aria-hidden="true" />}>
      <div className="flex items-center gap-2">
        <Show when="signed-out">
          <Link href="/sign-in" className={ghost}>
            Sign in
          </Link>
          <Link href="/sign-up" className={solid}>
            Create account
          </Link>
        </Show>
        <Show when="signed-in">
          {dashboardLink && (
            <Link href="/home" className={ghost}>
              Dashboard
            </Link>
          )}
          <UserButton />
        </Show>
      </div>
    </Suspense>
  );
}
