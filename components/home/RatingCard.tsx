import type { Profile } from "@/lib/engine";
import { ratingSeries, weekDelta } from "@/lib/engine";
import { fmtDelta, fmtInt } from "@/lib/format";
import { Card, CardHeader } from "./Card";
import { RatingChart } from "./RatingChart";

export function RatingCard({ profile }: { profile: Profile }) {
  const series = ratingSeries(profile, 60);
  const week = weekDelta(profile);
  const played = profile.rounds > 0;

  return (
    <Card label="Rating">
      <CardHeader title="Your rating" aside={series.length > 1 ? `Last ${series.length - 1} rounds` : "No rounds yet"} />
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <span className="font-mono text-[72px] font-semibold leading-none tracking-[-0.04em] md:text-[112px]">{fmtInt(profile.rating)}</span>
        <div className="flex flex-col items-start gap-2 pb-2">
          <span className={`text-base ${week.rounds === 0 ? "text-ink-tertiary" : week.delta >= 0 ? "text-accent" : "text-wrong"}`}>
            {week.rounds === 0 ? (played ? "No rounds this week" : "Play a duel to get rated") : `${fmtDelta(week.delta)} this week`}
          </span>
          {played && (
            <span className="label-caps rounded-full border border-gold px-3 py-1 text-gold">Peak {fmtInt(profile.peak)}</span>
          )}
        </div>
      </div>
      <RatingChart series={series} />
    </Card>
  );
}
