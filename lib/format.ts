export const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");

/** "+12", "−9" (real minus sign), "±0" */
export const fmtDelta = (d: number) => {
  const n = Math.round(d);
  return n > 0 ? `+${n}` : n < 0 ? `\u2212${Math.abs(n)}` : "\u00b10";
};

export const fmtSeconds = (ms: number, digits = 2) => `${(ms / 1000).toFixed(digits)}s`;

/** "= 399" for exact values, "≈ 0.583" when the display is rounded. */
export const fmtValue = (n: number) => {
  const rounded = +n.toFixed(3);
  const text = rounded.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return Math.abs(n - rounded) > 1e-9 ? `\u2248 ${text}` : `= ${text}`;
};
