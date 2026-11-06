"use client";

import { useEffect, useState } from "react";
import { ExprCard, type CardState } from "@/components/duel/ExprCard";

type Side = "left" | "right";

/** A static example from the real game: 47 × 23 = 1081, 51 × 21 = 1071. Try it with the arrow keys. */
const LEFT = { expression: "47 × 23", value: "1,081" };
const RIGHT = { expression: "51 × 21", value: "1,071" };
const ANSWER: Side = "left";

export function HeroDuel() {
  const [picked, setPicked] = useState<Side | null>(null);

  const pick = (side: Side) => setPicked((p) => p ?? side);
  const reset = () => setPicked(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement | null)?.closest("input,textarea,[contenteditable]")) return;
      if (e.key === "ArrowLeft") pick("left");
      else if (e.key === "ArrowRight") pick("right");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const stateFor = (side: Side): CardState => {
    if (picked === null) return "default";
    if (side === ANSWER) return "correct";
    return picked === side ? "wrong" : "default";
  };
  const reveal = picked !== null;

  return (
    <div className="flex flex-col items-center gap-5" aria-label="Interactive example of a duel">
      <div className="grid w-full gap-4 sm:grid-cols-2">
        <ExprCard compact side="left" expression={LEFT.expression} value={reveal ? LEFT.value : "?"} state={stateFor("left")} disabled={reveal} onSelect={() => pick("left")} />
        <ExprCard compact side="right" expression={RIGHT.expression} value={reveal ? RIGHT.value : "?"} state={stateFor("right")} disabled={reveal} onSelect={() => pick("right")} />
      </div>
      <p className="min-h-6 text-sm text-ink-secondary" aria-live="polite">
        {!reveal && "Which is bigger? Tap a card, or press ← / →."}
        {reveal && picked === ANSWER && "Right. Close pairs like this are what the game is made of."}
        {reveal && picked !== ANSWER && "Close one: they differ by only 10. The game adapts so most rounds are this tight."}
        {reveal && (
          <button type="button" onClick={reset} className="ml-3 rounded-key text-ink-tertiary underline-offset-4 hover:text-ink-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            Try again
          </button>
        )}
      </p>
    </div>
  );
}
