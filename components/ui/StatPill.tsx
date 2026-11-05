type StatPillProps = {
  label: string;
  value: string;
  tone?: "default" | "good";
};

/** Mirrors the Figma component "StatPill". */
export function StatPill({ label, value, tone = "default" }: StatPillProps) {
  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-line-subtle bg-bg-surface px-4 py-2">
      <span className="label-caps text-ink-tertiary">{label}</span>
      <span
        className={`font-mono text-base font-medium tabular-nums ${tone === "good" ? "text-accent" : "text-ink-primary"}`}
      >
        {value}
      </span>
    </div>
  );
}
