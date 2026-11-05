import { SKILL_LABEL, recentRounds, type Profile } from "@/lib/engine";
import { fmtSeconds } from "@/lib/format";
import { Card, CardHeader } from "./Card";

const SLOTS = 20;

export function RecentCard({ profile }: { profile: Profile }) {
  const rounds = recentRounds(profile, SLOTS);
  const correct = rounds.filter((r) => r.correct).length;
  const avg = rounds.length ? fmtSeconds(rounds.reduce((s, r) => s + r.timeMs, 0) / rounds.length) : null;

  return (
    <Card label="Recent rounds" className="gap-4 p-6">
      <CardHeader title="Last 20 rounds" aside={rounds.length ? `${correct} / ${rounds.length} correct \u00b7 avg ${avg}` : undefined} />
      <ul className="flex flex-wrap gap-2.5" aria-label="Recent rounds, oldest first">
        {Array.from({ length: SLOTS }, (_, i) => {
          const r = rounds[i - (SLOTS - rounds.length)];
          return (
            <li
              key={i}
              title={r ? `${SKILL_LABEL[r.skill]}: ${r.correct ? "correct" : "missed"} in ${fmtSeconds(r.timeMs)}` : undefined}
              aria-label={r ? (r.correct ? "Correct" : "Missed") : "Not played"}
              className={`h-5 w-5 rounded-full ${r ? (r.correct ? "bg-accent" : "bg-wrong") : "bg-bg-raised"}`}
            />
          );
        })}
      </ul>
      {!rounds.length && <p className="text-sm text-ink-tertiary">Your last 20 rounds show up here.</p>}
    </Card>
  );
}
