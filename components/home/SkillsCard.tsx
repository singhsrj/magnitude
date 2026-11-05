import { SKILLS, SKILL_LABEL, weakestSkill, type Profile } from "@/lib/engine";
import { fmtInt } from "@/lib/format";
import { Card, CardHeader } from "./Card";

export function SkillsCard({ profile }: { profile: Profile }) {
  const weakest = weakestSkill(profile);
  const rows = [...SKILLS].sort((a, b) => profile.skills[b] - profile.skills[a]);
  const lo = 1000;
  const hi = Math.max(1600, Math.max(...SKILLS.map((s) => profile.skills[s])) + 100);

  return (
    <Card label="Skills">
      <CardHeader title="Skills" aside={weakest ? `Weakest: ${SKILL_LABEL[weakest]}` : undefined} asideTone="wrong" />
      <ul className="flex flex-col gap-6">
        {rows.map((skill) => {
          const r = profile.skills[skill];
          const pct = Math.max(4, Math.min(100, ((r - lo) / (hi - lo)) * 100));
          const weak = skill === weakest;
          return (
            <li key={skill} className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="text-base">{SKILL_LABEL[skill]}</span>
                <span className={`font-mono text-base tabular-nums ${weak ? "text-wrong" : "text-ink-secondary"}`}>{fmtInt(r)}</span>
              </div>
              <div
                role="meter"
                aria-label={`${SKILL_LABEL[skill]} rating`}
                aria-valuemin={lo}
                aria-valuemax={hi}
                aria-valuenow={Math.round(r)}
                className="h-1.5 w-full overflow-hidden rounded-full bg-bg-raised"
              >
                <div className={`h-full rounded-full ${weak ? "bg-wrong" : "bg-accent"}`} style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
