import Link from "next/link";
import type { DailySummary } from "@/hooks/useDuel";
import { fmtDelta, fmtSeconds } from "@/lib/format";

export function DailySummaryView({ summary }: { summary: DailySummary }) {
  const { correct, total, avgMs, ratingDelta, alreadyDone } = summary;
  return (
    <div className="flex w-full max-w-[520px] animate-rise flex-col items-center gap-6 rounded-card border border-line-subtle bg-bg-surface p-8 text-center md:p-12">
      <h1 className="label-caps text-ink-secondary">{alreadyDone ? "Today\u2019s set is done" : "Daily set complete"}</h1>
      <p className="font-mono text-[72px] font-semibold leading-none tracking-[-0.04em]">
        {correct}
        <span className="text-ink-tertiary"> / {total}</span>
      </p>
      <p className="text-base text-ink-secondary">
        {fmtSeconds(avgMs)} per problem{alreadyDone ? "" : ` \u00b7 rating ${fmtDelta(ratingDelta)}`}
      </p>
      {alreadyDone && <p className="text-sm text-ink-tertiary">A new set unlocks at midnight.</p>}
      <div className="flex w-full flex-col gap-3 sm:flex-row">
        <Link
          href="/"
          className="inline-flex h-14 flex-1 items-center justify-center rounded-control bg-accent text-base font-semibold text-ink-onAccent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
        >
          Back home
        </Link>
        <Link
          href="/duel"
          className="inline-flex h-14 flex-1 items-center justify-center rounded-control border border-line-strong text-base font-medium text-ink-primary hover:border-ink-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
        >
          Keep practising
        </Link>
      </div>
    </div>
  );
}
