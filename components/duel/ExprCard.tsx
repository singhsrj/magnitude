import type { Side } from "@/lib/engine";
import { KeyCap } from "@/components/ui/KeyCap";

export type CardState = "default" | "correct" | "wrong";

type ExprCardProps = {
  side: Side;
  expression: string;
  /** Shown under the expression: "?" while playing, the real value on reveal */
  value: string;
  state: CardState;
  disabled: boolean;
  onSelect: () => void;
};

/** Mirrors the Figma component set "ExprCard" (State = Default | Correct | Wrong). */
const SURFACE: Record<CardState, string> = {
  default: "border border-line-subtle bg-bg-surface enabled:hover:border-line-strong",
  correct: "border-2 border-correct bg-correct-dim shadow-glow",
  wrong: "animate-shake border-2 border-wrong bg-wrong-dim",
};
const VALUE_COLOR: Record<CardState, string> = {
  default: "text-ink-tertiary",
  correct: "text-correct",
  wrong: "text-ink-secondary",
};
const BADGE: Record<CardState, { text: string; color: string } | null> = {
  default: null,
  correct: { text: "Correct", color: "text-correct" },
  wrong: { text: "Wrong", color: "text-wrong" },
};

export function ExprCard({ side, expression, value, state, disabled, onSelect }: ExprCardProps) {
  const badge = BADGE[state];
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-label={`Choose ${expression}`}
      className={`flex h-[200px] w-full max-w-[520px] flex-col justify-between rounded-card p-6 text-left transition-colors duration-150 disabled:cursor-default md:h-[340px] md:p-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent ${SURFACE[state]}`}
    >
      <span className="flex w-full items-center justify-between">
        <KeyCap glyph={side === "left" ? "←" : "→"} />
        {badge && <span className={`label-caps ${badge.color}`}>{badge.text}</span>}
      </span>
      <span className="text-center font-mono text-[40px] font-medium tracking-[-0.02em] text-ink-primary md:text-[64px]">
        {expression}
      </span>
      <span className={`text-center font-mono text-base ${VALUE_COLOR[state]}`}>{value}</span>
    </button>
  );
}
