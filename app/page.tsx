import { Show } from "@clerk/nextjs";
import Link from "next/link";
import { Suspense } from "react";
import { AuthControls } from "@/components/landing/AuthControls";
import { HeroDuel } from "@/components/landing/HeroDuel";
import { KeyCap } from "@/components/ui/KeyCap";
import { Logo } from "@/components/ui/Logo";

const primary =
  "inline-flex h-14 items-center justify-center rounded-card bg-accent px-8 text-lg font-semibold text-ink-onAccent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent";
const secondary =
  "inline-flex h-14 items-center justify-center rounded-card border border-line-strong bg-bg-surface px-8 text-lg font-medium text-ink-primary hover:border-ink-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent";

const STEPS = [
  { key: "1", title: "Two expressions", body: "Each round shows two calculations, like 47 × 23 and 51 × 21. No calculator, no pen." },
  { key: "2", title: "One keypress", body: "Press ← or → for the bigger one. You have eight seconds, and faster correct answers score more." },
  { key: "3", title: "A rating that adapts", body: "An Elo rating tracks you and picks the next problem near your edge, so you win about 70% of the time." },
];

const SKILLS = [
  { name: "Multiplication", sample: "38 × 27" },
  { name: "Percentages", sample: "18% of 450" },
  { name: "Fractions", sample: "7/12 vs 5/9" },
  { name: "Powers", sample: "7³ vs 2⁸" },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-6 md:px-12">
        <header className="flex items-center justify-between py-6">
          <Logo />
          <AuthControls />
        </header>

        {/* hero */}
        <section className="grid items-center gap-12 pb-20 pt-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:pt-16">
          <div className="flex flex-col items-start gap-6">
            <p className="label-caps text-accent">Mental math, timed</p>
            <h1 className="text-[44px] font-semibold leading-[1.05] tracking-[-0.03em] md:text-[64px]">
              Which is <span className="text-accent">bigger</span>?
            </h1>
            <p className="max-w-[44ch] text-lg leading-relaxed text-ink-secondary">
              Two expressions, one keypress. Magnitude measures how fast and how well you estimate, and keeps every round
              at the edge of what you can do quickly.
            </p>
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <Link href="/duel" className={primary}>
                Play now
              </Link>
              <Suspense fallback={<span className="h-14 w-44" aria-hidden="true" />}>
                <Show when="signed-out">
                  <Link href="/sign-up" className={secondary}>
                    Create account
                  </Link>
                </Show>
                <Show when="signed-in">
                  <Link href="/home" className={secondary}>
                    Open dashboard
                  </Link>
                </Show>
              </Suspense>
            </div>
            <p className="flex items-center gap-2 text-sm text-ink-tertiary">
              <KeyCap glyph={"←"} size="sm" />
              <KeyCap glyph={"→"} size="sm" />
              <span>No account needed to play.</span>
            </p>
          </div>
          <HeroDuel />
        </section>

        {/* how it works */}
        <section aria-labelledby="how" className="border-t border-line-subtle py-16">
          <h2 id="how" className="label-caps text-ink-tertiary">
            How it works
          </h2>
          <ol className="mt-8 grid gap-4 md:grid-cols-3">
            {STEPS.map((s) => (
              <li key={s.key} className="flex flex-col gap-3 rounded-card border border-line-subtle bg-bg-surface p-6">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-key border border-line-strong bg-bg-raised font-mono text-sm">
                  {s.key}
                </span>
                <h3 className="text-xl font-semibold tracking-[-0.01em]">{s.title}</h3>
                <p className="leading-relaxed text-ink-secondary">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* skills */}
        <section aria-labelledby="skills" className="border-t border-line-subtle py-16">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 id="skills" className="label-caps text-ink-tertiary">
                Four skills, four ratings
              </h2>
              <p className="mt-3 max-w-[52ch] text-2xl font-semibold tracking-[-0.02em]">
                Your weakest skill shows up more often, so practice goes where it helps.
              </p>
            </div>
          </div>
          <ul className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-4">
            {SKILLS.map((s) => (
              <li key={s.name} className="flex flex-col gap-2 rounded-card border border-line-subtle bg-bg-surface p-5">
                <span className="text-sm text-ink-secondary">{s.name}</span>
                <span className="font-mono text-xl text-ink-primary">{s.sample}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* closing call to action */}
        <section className="mb-20 flex flex-col items-center gap-6 rounded-card border border-line-subtle bg-bg-surface px-6 py-14 text-center">
          <h2 className="text-3xl font-semibold tracking-[-0.02em] md:text-4xl">Find your level.</h2>
          <p className="max-w-[46ch] text-ink-secondary">
            Start a duel right away, or make an account to keep it as yours. A daily set of ten problems is the same for
            everyone, every day.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link href="/duel" className={primary}>
              Start a duel
            </Link>
            <Link href="/duel/daily" className={secondary}>
              Try today&rsquo;s set
            </Link>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex w-full max-w-[1200px] items-center justify-between px-6 pb-8 text-sm text-ink-tertiary md:px-12">
        <span>&copy; Magnitude</span>
        <Link href="/home" className="hover:text-ink-secondary">
          Dashboard
        </Link>
      </footer>
    </div>
  );
}
