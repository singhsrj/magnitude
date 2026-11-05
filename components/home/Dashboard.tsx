"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Profile } from "@/lib/engine";
import { loadProfile, resetProfile } from "@/lib/profile";
import { Logo } from "@/components/ui/Logo";
import { DailyCard } from "./DailyCard";
import { RatingCard } from "./RatingCard";
import { RecentCard } from "./RecentCard";
import { SkillsCard } from "./SkillsCard";

/** Mirrors the Figma frame "Home — Dashboard". */
export function Dashboard() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);

  // localStorage only exists in the browser, so the dashboard fills in after mount.
  useEffect(() => {
    setProfile(loadProfile());
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement | null)?.closest("a,button")) return; // focused controls keep their own behaviour
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        router.push("/duel");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const onReset = () => {
    if (window.confirm("Reset your rating and history on this device? This can\u2019t be undone.")) setProfile(resetProfile());
  };

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[1440px] flex-col px-6 py-6 md:px-12">
      <header className="flex items-center justify-between py-1">
        <Logo />
        <span className="hidden text-sm text-ink-tertiary md:inline">Space &middot; start</span>
      </header>

      {profile && (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,720fr)_minmax(0,592fr)] lg:items-start">
          <div className="flex flex-col gap-6">
            <RatingCard profile={profile} />
            <Link
              href="/duel"
              className="inline-flex h-[76px] w-full items-center justify-center gap-4 rounded-card bg-accent text-xl font-semibold text-ink-onAccent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            >
              {profile.rounds === 0 ? "Start your first duel" : "Start duel"}
              <span className="hidden text-sm font-normal opacity-60 md:inline">Space</span>
            </Link>
            <RecentCard profile={profile} />
          </div>
          <div className="flex flex-col gap-6">
            <SkillsCard profile={profile} />
            <DailyCard profile={profile} />
          </div>
        </div>
      )}

      <footer className="mt-auto flex justify-end pt-10 text-sm text-ink-tertiary">
        <button type="button" onClick={onReset} className="rounded-key px-2 py-1 hover:text-ink-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
          Reset progress
        </button>
      </footer>
    </main>
  );
}
