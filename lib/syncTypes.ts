import type { Side, Skill } from "./engine";

/** A practice session ticket issued by the server: the seed makes every problem reproducible there. */
export interface Ticket {
  sessionId: string;
  seed: number;
  /** ms since epoch */
  expiresAt: number;
}

interface EventBase {
  /** null = timed out */
  choice: Side | null;
  /** Whole ms, already passed through normalizeTime (the same value the local Elo used). */
  timeMs: number;
  /** Client clock, ms since epoch, when the answer was given */
  at: number;
  /** What the client saw. The server rebuilds the problem and rejects the event if these differ. */
  problemId: string;
  skill: Skill;
  problemRating: number;
  /** Informational: the server grades from `choice`. Also used to re-apply the round locally. */
  correct: boolean;
}

export interface PracticeEvent extends EventBase {
  kind: "practice";
  sessionId: string;
  index: number;
  /** Round 0 only: the generation skills the session started from */
  startSkills?: Record<Skill, number>;
  /** Player's own calendar day, "YYYY-MM-DD" */
  localDate: string;
}

export interface DailyEvent extends EventBase {
  kind: "daily";
  /** The daily set's date key, "YYYY-MM-DD" */
  date: string;
  index: number;
}

export type OutboxEvent = PracticeEvent | DailyEvent;

/** Idempotency key: the same key is never applied twice by the server. */
export function eventKey(e: { kind: "practice" | "daily"; sessionId?: string | null; date?: string | null; index: number }): string {
  return e.kind === "practice" ? `p:${e.sessionId}:${e.index}` : `d:${e.date}:${e.index}`;
}

export type RejectReason =
  | "unknown_session" | "expired" | "session_broken" | "gap" | "mismatch" | "bad_start"
  | "implausible_time" | "bad_date" | "out_of_range";

export interface SyncResponse {
  acked: { kind: "practice" | "daily"; sessionId?: string | null; date?: string | null; index: number }[];
  rejected: { kind: "practice" | "daily"; sessionId?: string | null; date?: string | null; index: number; reason: RejectReason }[];
  /** Same shape as the local `Profile` */
  profile: unknown;
}
