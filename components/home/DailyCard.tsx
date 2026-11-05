import Link from "next/link";
import { DAILY_LENGTH, dateKey, dayIntensity, dayStreak, lastDays, type Profile } from "@/lib/engine";
import { Card, CardHeader } from "./Card";

function untilMidnight(now: Date): string {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const mins = Math.max(0, Math.round((next.getTime() - now.getTime()) / 60000));
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m`;
}

export function DailyCard({ profile }: { profile: Profile }) {
  const now = new Date();
  const today = dateKey(now);
  const done = profile.daily[today];
  const days = lastDays(14, today);
  const streak = dayStreak(profile, today);

  return (
    <Card label="Daily set">
      <CardHeader title="Daily set" />
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-base">{done ? `Done \u00b7 ${done.correct} of ${done.total}` : `${DAILY_LENGTH} problems`}</span>
          <span className="text-sm text-ink-tertiary">{done ? "New set" : "Resets"} in {untilMidnight(now)}</span>
        </div>
        {done ? (
          <span className="inline-flex h-12 items-center rounded-control border border-line-subtle px-6 text-base text-ink-tertiary">Done</span>
        ) : (
          <Link
            href="/duel/daily"
            className="inline-flex h-12 items-center rounded-control border border-line-strong px-6 text-base font-medium hover:border-ink-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          >
            Play
          </Link>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex gap-2" role="img" aria-label={`Activity over the last 14 days. ${streak}-day streak.`}>
          {days.map((key) => {
            const rounds = profile.days[key]?.rounds ?? 0;
            const intensity = dayIntensity(profile, key);
            return (
              <span
                key={key}
                title={`${key}: ${rounds} ${rounds === 1 ? "round" : "rounds"}`}
                className={`h-7 min-w-0 max-w-7 flex-1 rounded-lg ${intensity === 0 ? "bg-bg-raised" : ""} ${key === today ? "ring-1 ring-ink-secondary" : ""}`}
                style={intensity > 0 ? { backgroundColor: `rgba(124, 245, 192, ${intensity})` } : undefined}
              />
            );
          })}
        </div>
        <span className="text-sm text-ink-tertiary">
          Last 14 days{streak > 0 ? ` \u00b7 ${streak}-day streak` : " \u00b7 play a round to start a streak"}
        </span>
      </div>
    </Card>
  );
}
