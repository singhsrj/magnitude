"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DAILY_LENGTH,
  ROUND_LIMIT_MS,
  SESSION_MAX_ROUNDS,
  applyRound,
  dailyProblem,
  dateKey,
  expectedScore,
  newProfile,
  nextGenSkills,
  normalizeTime,
  recordDaily,
  sessionProblem,
  type Problem,
  type Profile,
  type Side,
  type Skill,
} from "@/lib/engine";
import { loadProfile, saveProfile } from "@/lib/profile";
import { SYNC_ENABLED, acquireTicket, flush, onProfile, pushEvent, returnTicket, startSync } from "@/lib/sync";
import type { Ticket } from "@/lib/syncTypes";

export type DuelMode = "practice" | "daily";
export type Phase = "loading" | "question" | "result" | "summary";

export interface RoundResult {
  /** null = timed out */
  chosen: Side | null;
  correct: boolean;
  timeMs: number;
  delta: number;
  expected: number;
  score: number;
}

export interface DailySummary {
  correct: number;
  total: number;
  avgMs: number;
  /** Rating change across the set (0 when showing an already-finished day) */
  ratingDelta: number;
  alreadyDone: boolean;
}

/** A practice session: problems come from the ticket's seed, so the server can replay it later. */
interface Session {
  ticket: Ticket;
  /** Index of the round being played (0-based) */
  index: number;
  /** Generation skills before this round; they roll forward with the session's own rounds */
  gen: Record<Skill, number>;
  /** What round 0 started from (sent with the first event) */
  startSkills: Record<Skill, number>;
}

/**
 * The duel state machine: loading -> question -> result -> question ... (-> summary in daily mode).
 * Refs mirror state so the stable callbacks (keyboard, timeout) never read stale values.
 *
 * Nothing between a keypress and the feedback touches the network: problems come from a seeded session,
 * grading and Elo run here, and each answer is appended to a local outbox that syncs in the background.
 */
export function useDuel(mode: DuelMode = "practice") {
  const [profile, setProfile] = useState<Profile>(() => newProfile());
  const [problem, setProblem] = useState<Problem | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [result, setResult] = useState<RoundResult | null>(null);
  const [runKey, setRunKey] = useState(0);
  const [index, setIndex] = useState(0);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [slowToStart, setSlowToStart] = useState(false);

  const profileRef = useRef(profile);
  const problemRef = useRef<Problem | null>(null);
  const phaseRef = useRef<Phase>("loading");
  const startedAt = useRef(0);
  const indexRef = useRef(0);
  const dailyKeyRef = useRef("");
  const dailyRounds = useRef<{ correct: boolean; timeMs: number }[]>([]);
  const startRating = useRef(0);
  const sessionRef = useRef<Session | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const begin = useCallback(
    (at: number) => {
      let next: Problem;
      if (mode === "daily") {
        next = dailyProblem(dailyKeyRef.current, at);
      } else {
        const s = sessionRef.current!;
        next = sessionProblem(s.ticket.seed, s.index, s.gen);
      }
      indexRef.current = at;
      problemRef.current = next;
      phaseRef.current = "question";
      startedAt.current = performance.now();
      setIndex(at);
      setProblem(next);
      setResult(null);
      setPhase("question");
      setRunKey((k) => k + 1);
    },
    [mode],
  );

  /** Takes a ticket (instantly, when one is in the pool) and starts a fresh practice session from it. */
  const startSession = useCallback(async (signal: AbortSignal): Promise<boolean> => {
    const ticket = await acquireTicket(signal);
    if (!ticket) return false;
    if (signal.aborted) {
      returnTicket(ticket); // the screen went away first (also what React StrictMode does on mount)
      return false;
    }
    const skills = { ...profileRef.current.skills };
    sessionRef.current = { ticket, index: 0, gen: skills, startSkills: { ...skills } };
    return true;
  }, []);

  // Load the saved profile after mount (localStorage doesn't exist during SSR).
  useEffect(() => {
    const saved = loadProfile();
    profileRef.current = saved;
    setProfile(saved);
    startRating.current = saved.rating;
    dailyRounds.current = [];

    const abort = new AbortController();
    abortRef.current = abort;
    let stopProfileUpdates: (() => void) | undefined;
    if (SYNC_ENABLED) {
      // A sync finished: the server's profile (plus rounds it hasn't acknowledged) replaces ours.
      stopProfileUpdates = onProfile((p) => {
        profileRef.current = p;
        setProfile(p);
      });
      startSync();
    }

    if (mode === "daily") {
      const key = dateKey();
      dailyKeyRef.current = key;
      const done = saved.daily[key];
      if (done) {
        phaseRef.current = "summary";
        setSummary({ correct: done.correct, total: done.total, avgMs: done.timeMs / done.total, ratingDelta: 0, alreadyDone: true });
        setPhase("summary");
      } else {
        begin(0);
      }
    } else {
      void startSession(abort.signal).then((ok) => {
        if (ok) begin(0);
      });
    }

    return () => {
      abort.abort();
      stopProfileUpdates?.();
      if (SYNC_ENABLED) void flush({ keepalive: true }); // leaving: send what's waiting (a no-op when nothing is)
    };
  }, [begin, mode, startSession]);

  // Only when the backend is unreachable and the ticket pool is empty does starting take noticeable time.
  useEffect(() => {
    if (phase !== "loading" || !SYNC_ENABLED) {
      setSlowToStart(false);
      return;
    }
    const id = window.setTimeout(() => setSlowToStart(true), 3000);
    return () => window.clearTimeout(id);
  }, [phase]);

  const answer = useCallback(
    (side: Side | null) => {
      const current = problemRef.current;
      if (!current || phaseRef.current !== "question") return;
      const at = Date.now();
      // The same whole-ms value drives the local Elo and is sent to the server, so both compute identical ratings.
      const timeMs = side === null ? ROUND_LIMIT_MS : normalizeTime(performance.now() - startedAt.current);
      const correct = side !== null && side === current.answer;
      const out = applyRound(profileRef.current, current, correct, timeMs, at);
      dailyRounds.current.push({ correct, timeMs });
      profileRef.current = out.profile;
      phaseRef.current = "result";
      saveProfile(out.profile);

      // Written to the outbox before the result is shown; sent later, in the background.
      const base = { choice: side, timeMs, at, problemId: current.id, skill: current.skill, problemRating: current.rating, correct };
      if (mode === "daily") {
        pushEvent({ kind: "daily", date: dailyKeyRef.current, index: indexRef.current, ...base });
      } else {
        const s = sessionRef.current!;
        pushEvent({
          kind: "practice",
          sessionId: s.ticket.sessionId,
          index: s.index,
          ...(s.index === 0 ? { startSkills: s.startSkills } : {}),
          localDate: dateKey(at),
          ...base,
        });
        s.gen = nextGenSkills(s.gen, current, correct, timeMs);
        s.index += 1;
      }

      setProfile(out.profile);
      setResult({ chosen: side, correct, timeMs, delta: out.delta, expected: out.expected, score: out.score });
      setPhase("result");
    },
    [mode],
  );

  const finishDaily = useCallback(() => {
    const rounds = dailyRounds.current;
    const correct = rounds.filter((r) => r.correct).length;
    const timeMs = rounds.reduce((s, r) => s + r.timeMs, 0);
    const updated = recordDaily(profileRef.current, dailyKeyRef.current, { correct, total: rounds.length, timeMs });
    profileRef.current = updated;
    saveProfile(updated);
    setProfile(updated);
    phaseRef.current = "summary";
    setSummary({
      correct,
      total: rounds.length,
      avgMs: rounds.length ? timeMs / rounds.length : 0,
      ratingDelta: updated.rating - startRating.current,
      alreadyDone: false,
    });
    setPhase("summary");
  }, []);

  const next = useCallback(() => {
    if (phaseRef.current !== "result") return;
    if (mode === "daily") {
      if (indexRef.current + 1 >= DAILY_LENGTH) finishDaily();
      else begin(indexRef.current + 1);
      return;
    }
    if (sessionRef.current && sessionRef.current.index >= SESSION_MAX_ROUNDS) {
      // A very long session: the server caps one at SESSION_MAX_ROUNDS, so continue on a fresh ticket.
      phaseRef.current = "loading";
      setPhase("loading");
      const signal = abortRef.current?.signal ?? new AbortController().signal;
      void startSession(signal).then((ok) => {
        if (ok) begin(0);
      });
      return;
    }
    begin(0);
  }, [begin, finishDaily, mode, startSession]);

  // Out of time counts as a miss.
  useEffect(() => {
    if (phase !== "question") return;
    const id = window.setTimeout(() => answer(null), ROUND_LIMIT_MS);
    return () => window.clearTimeout(id);
  }, [phase, runKey, answer]);

  const winChance = result ? result.expected : problem ? expectedScore(profile.rating, problem.rating) : null;
  const lastInSet = mode === "daily" && index + 1 >= DAILY_LENGTH;

  return { profile, problem, phase, result, runKey, winChance, answer, next, index, summary, lastInSet, connecting: slowToStart };
}
