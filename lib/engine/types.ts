export type Skill = "multiplication" | "percentages" | "fractions" | "powers";
export const SKILLS: Skill[] = ["multiplication", "percentages", "fractions", "powers"];
export const SKILL_LABEL: Record<Skill, string> = {
  multiplication: "Multiplication",
  percentages: "Percentages",
  fractions: "Fractions",
  powers: "Powers",
};

export type Side = "left" | "right";

export interface Expr {
  /** What the player sees, e.g. "17 × 23" */
  text: string;
  /** The true numeric value, used to decide the answer and for the reveal */
  value: number;
}

export interface Problem {
  id: string;
  skill: Skill;
  left: Expr;
  right: Expr;
  /** Difficulty on the same scale as player ratings */
  rating: number;
  /** Which side is bigger */
  answer: Side;
}

export interface RoundRecord {
  at: number;
  skill: Skill;
  correct: boolean;
  timeMs: number;
  delta: number;
  problemRating: number;
}

/** Rounds played on one local calendar day (drives the streak heat strip). */
export interface DayStat {
  rounds: number;
  correct: number;
}

/** Result of a completed daily set. */
export interface DailyResult {
  correct: number;
  total: number;
  timeMs: number;
}

export interface Profile {
  rating: number;
  peak: number;
  skills: Record<Skill, number>;
  streak: number;
  bestStreak: number;
  rounds: number;
  /** Most recent rounds, newest last (capped) */
  history: RoundRecord[];
  /** Activity per local date, keyed "YYYY-MM-DD" */
  days: Record<string, DayStat>;
  /** Completed daily sets, keyed by date */
  daily: Record<string, DailyResult>;
}
