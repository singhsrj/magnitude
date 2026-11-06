import Link from "next/link";
import { Suspense } from "react";
import { Logo } from "@/components/ui/Logo";

/** Frame for Clerk's sign-in and sign-up screens: the app's logo, a way back, and the card centred. */
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[1200px] flex-col px-6 py-6 md:px-12">
      <header className="flex items-center justify-between py-1">
        <Logo />
        <Link href="/duel" className="text-sm text-ink-tertiary hover:text-ink-secondary">
          Play without an account
        </Link>
      </header>
      <div className="flex flex-1 items-center justify-center py-10">
        <Suspense>{children}</Suspense>
      </div>
    </main>
  );
}
