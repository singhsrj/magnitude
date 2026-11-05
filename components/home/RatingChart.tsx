"use client";

import { useId } from "react";
import { fmtInt } from "@/lib/format";

const W = 656;
const H = 220;

/** Rating over recent rounds. Points come from ratingSeries(); nothing is stored for the chart. */
export function RatingChart({ series }: { series: number[] }) {
  const gradientId = useId().replace(/:/g, "");

  if (series.length < 3) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-control border border-dashed border-line-subtle text-center text-sm text-ink-tertiary">
        Your rating curve appears after a few rounds.
      </div>
    );
  }

  const min = Math.min(...series);
  const max = Math.max(...series);
  const pad = Math.max(8, (max - min) * 0.12);
  const lo = min - pad;
  const hi = max + pad;
  const x = (i: number) => (i / (series.length - 1)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const line = series.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const lastY = y(series[series.length - 1]);

  return (
    <div
      className="relative h-[220px] w-full"
      role="img"
      aria-label={`Rating over the last ${series.length - 1} rounds: from ${fmtInt(series[0])} to ${fmtInt(series[series.length - 1])}`}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7CF5C0" stopOpacity="0.28" />
            <stop offset="1" stopColor="#7CF5C0" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, H / 2, H - 1].map((gy) => (
          <line key={gy} x1="0" x2={W} y1={gy} y2={gy} stroke="#232837" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ))}
        <path d={`${line} L ${W} ${H} L 0 ${H} Z`} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke="#7CF5C0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      {/* End marker is HTML so it stays round while the SVG stretches to the card width */}
      <span aria-hidden="true" className="absolute -translate-y-1/2 rounded-full bg-accent/20" style={{ right: -8, top: `${(lastY / H) * 100}%`, width: 28, height: 28, marginRight: -6 }} />
      <span aria-hidden="true" className="absolute -translate-y-1/2 rounded-full bg-accent" style={{ right: -2, top: `${(lastY / H) * 100}%`, width: 12, height: 12 }} />
    </div>
  );
}
