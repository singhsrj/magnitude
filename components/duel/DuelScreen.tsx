"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { DAILY_LENGTH, ROUND_LIMIT_MS, SKILL_LABEL, type Side } from "@/lib/engine";
import { useDuel, type DuelMode } from "@/hooks/useDuel";
import { fmtDelta, fmtInt, fmtSeconds, fmtValue } from "@/lib/format";
import { Logo } from "@/components/ui/Logo";
import { StatPill } from "@/components/ui/StatPill";
import { DailySummaryView } from "./DailySummary";
import { ExprCard, type CardState } from "./ExprCard";
import { TimerBar } from "./TimerBar";

export function DuelScreen({ mode = "practice" }: { mode?: DuelMode }) {
  const router = useRouter();
  const { profile, problem, phase, result, runKey, winChance, answer, next, index, summary, lastInSet, connecting } = useDuel(mode);

  // Keyboard: ← / → answer, Space or Enter continues, Esc leaves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") { router.push("/"); return; }
      if ((e.target as HTMLElement | null)?.closest("a")) return; // let focused links act normally
      if (e.key === "ArrowLeft") { e.preventDefault(); answer("left"); }
      else if (e.key === "ArrowRight") { e.preventDefault(); answer("right"); }
      else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        if (phase === "summary") router.push("/");
        else next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [answer, next, router, phase]);

  const inResult = phase === "result" && result && problem;

  const cardState = (side: Side): CardState => {
    if (!inResult) return "default";
    if (side === problem.answer) return "correct";
    return result.chosen === side ? "wrong" : "default";
  };

  const recent = profile.history.slice(-20);
  const avg = recent.length ? fmtSeconds(recent.reduce((s, r) => s + r.timeMs, 0) / recent.length) : "\u2014";

  const status = !inResult
    ? "Which is bigger?"
    : result.chosen === null
      ? "Time\u2019s up"
      : result.correct
        ? `Correct \u00b7 ${fmtSeconds(result.timeMs)}`
        : `Not quite \u00b7 ${fmtSeconds(result.timeMs)}`;
  const statusColor = !inResult ? "text-ink-secondary" : result.correct ? "text-accent" : "text-wrong";

  const renderChoice = (side: Side) => {
    const expr = problem ? problem[side] : null;
    const chosenHere = inResult && result.chosen === side;
    return (
      <div className="flex w-full flex-col items-center gap-4">
        <div className="flex h-12 items-center justify-center gap-3 md:h-14" aria-hidden={!chosenHere}>
          {chosenHere && (
            <>
              <span className={`animate-rise font-mono text-[40px] font-semibold leading-none ${result.correct ? "text-accent" : "text-wrong"}`}>
                {fmtDelta(result.delta)}
              </span>
              <span className="animate-rise text-sm text-ink-secondary">
                Elo{result.correct && result.score >= 0.9 ? " \u00b7 speed bonus" : result.correct ? "" : " \u00b7 missed"}
              </span>
            </>
          )}
        </div>
        <ExprCard
          side={side}
          expression={expr ? expr.text : "\u2026"}
          value={inResult && expr ? fmtValue(expr.value) : "?"}
          state={cardState(side)}
          disabled={phase !== "question"}
          onSelect={() => answer(side)}
        />
      </div>
    );
  };

  const hint = inResult
    ? lastInSet ? "Space to see your score" : "Space to continue"
    : "Press \u2190 or \u2192. Faster answers move your rating more.";

  return (
    <main className="flex min-h-dvh flex-col">
      <header className="flex flex-wrap items-center justify-between gap-4 px-6 py-5 md:px-12 md:py-6">
        <Logo />
        <div className="flex flex-wrap items-center gap-3">
          <StatPill label="Rating" value={fmtInt(profile.rating)} tone={inResult && result.delta > 0 ? "good" : "default"} />
          <StatPill label="Streak" value={String(profile.streak)} />
          <StatPill label="Avg" value={avg} />
        </div>
        <Link href="/" className="hidden text-sm text-ink-tertiary hover:text-ink-secondary md:inline">
          Esc &middot; menu
        </Link>
      </header>

      {phase === "summary" && summary ? (
        <section className="flex flex-1 flex-col items-center justify-center px-6 py-8">
          <DailySummaryView summary={summary} />
        </section>
      ) : (
        <>
          <TimerBar
            durationMs={ROUND_LIMIT_MS}
            runKey={runKey}
            running={phase === "question"}
            tone={!inResult ? "idle" : result.correct ? "correct" : "wrong"}
          />

          <section className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-8">
            <p className={`label-caps ${statusColor}`} aria-live="polite">{status}</p>

            <div className="flex w-full max-w-[1120px] flex-col items-center gap-2 md:flex-row md:items-start md:justify-center md:gap-6">
              {renderChoice("left")}
              <div
                aria-hidden="true"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line-subtle bg-bg-raised text-xs uppercase tracking-[0.12em] text-ink-tertiary md:mt-[214px] md:h-14 md:w-14"
              >
                vs
              </div>
              {renderChoice("right")}
            </div>

            <p className="text-center text-base text-ink-tertiary">{hint}</p>
          </section>

          <footer className="flex flex-wrap items-center justify-between gap-2 px-6 py-5 text-sm md:px-12 md:py-6">
            <span className="text-ink-secondary">
              {!problem
                ? connecting
                  ? "Connecting\u2026 can\u2019t reach the server yet, retrying"
                  : "Loading\u2026"
                : mode === "daily"
                  ? `Daily set \u00b7 ${index + 1} of ${DAILY_LENGTH} \u00b7 ${SKILL_LABEL[problem.skill]}`
                  : `Round ${profile.rounds + (inResult ? 0 : 1)} \u00b7 ${SKILL_LABEL[problem.skill]} \u00b7 problem rated ${fmtInt(problem.rating)}`}
            </span>
            <span className="text-ink-tertiary">{winChance === null ? "" : `${Math.round(winChance * 100)}% expected score`}</span>
          </footer>
        </>
      )}
    </main>
  );
}
