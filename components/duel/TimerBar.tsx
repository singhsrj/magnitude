type TimerBarProps = {
  durationMs: number;
  /** Changing this remounts the bar, restarting the countdown */
  runKey: number;
  running: boolean;
  tone: "idle" | "correct" | "wrong";
};

const TONE: Record<TimerBarProps["tone"], string> = {
  idle: "bg-ink-secondary",
  correct: "bg-accent",
  wrong: "bg-wrong",
};

export function TimerBar({ durationMs, runKey, running, tone }: TimerBarProps) {
  return (
    <div className="px-6 py-2 md:px-12">
      <div className="h-1 w-full overflow-hidden rounded-full bg-bg-raised" aria-hidden="true">
        <div
          key={runKey}
          className={`h-full rounded-full animate-timer ${TONE[tone]}`}
          style={{ animationDuration: `${durationMs}ms`, animationPlayState: running ? "running" : "paused" }}
        />
      </div>
    </div>
  );
}
