import type { ReactNode } from "react";

export function Card({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={label} className={`flex flex-col gap-6 rounded-card border border-line-subtle bg-bg-surface p-6 md:p-8 ${className}`}>
      {children}
    </section>
  );
}

export function CardHeader({ title, aside, asideTone = "muted" }: { title: string; aside?: string; asideTone?: "muted" | "wrong" }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <h2 className="label-caps text-ink-secondary">{title}</h2>
      {aside && <span className={`text-sm ${asideTone === "wrong" ? "label-caps text-wrong" : "text-ink-tertiary"}`}>{aside}</span>}
    </div>
  );
}
