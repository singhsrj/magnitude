"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DAILY_LENGTH,
  ROUND_LIMIT_MS,
  applyRound,
  dailyProblem,
  dateKey,
  expectedScore,
  generateProblem,
  newProfile,
  pickSkill,
  recordDaily,
  targetProblemRating,
  type Problem,
  type Profile,
  type Side,
} from "@/lib/engine";
import { loadProfile, saveProfile } from "@/lib/profile";

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

/**
 * The duel state machine: loading -> question -> result -> question ... (-> summary in daily mode).
 * Refs mirror state so the stable callbacks (keyboard, timeout) never read stale values.
 */
export function useDuel(mode: DuelMode = "practice") {
  const [profile, setProfile] = useState<Profile>(() => newProfile());
  const [problem, setProblem] = useState<Problem | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [result, setResult] = useState<RoundResult | null>(null);
  const [runKey, setRunKey] = useState(0);
  const [index, setIndex] = useState(0);
  const [summary, setSummary] = useState<DailySummary | null>(null);

  const profileRef = useRef(profile);
  const problemRef = useRef<Problem | null>(null);
  const phaseRef = useRef<Phase>("loading");
  const startedAt = useRef(0);
  const indexRef = useRef(0);
  const dailyKeyRef = useRef("");
  const dailyRounds = useRef<{ correct: boolean; timeMs: number }[]>([]);
  const startRating = useRef(0);

  const begin = useCallback(
    (p: Profile, at: number) => {
      let next: Problem;
      if (mode === "daily") {
        next = dailyProblem(dailyKeyRef.current, at);
      } else {
        const skill = pickSkill(Math.random, p.skills);
        next = generateProblem({ skill, targetRating: targetProblemRating(p.skills[skill]), rng: Math.random });
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

  // Load the saved profile after mount (localStorage doesn't exist during SSR).
  useEffect(() => {
    const saved = loadProfile();
    profileRef.current = saved;
    setProfile(saved);
    startRating.current = saved.rating;
    dailyRounds.current = [];

    if (mode === "daily") {
      const key = dateKey();
      dailyKeyRef.current = key;
      const done = saved.daily[key];
      if (done) {
        phaseRef.current = "summary";
        setSummary({ correct: done.correct, total: done.total, avgMs: done.timeMs / done.total, ratingDelta: 0, alreadyDone: true });
        setPhase("summary");
        return;
      }
    }
    begin(saved, 0);
  }, [begin, mode]);

  const answer = useCallback((side: Side | null) => {
    const current = problemRef.current;
    if (!current || phaseRef.current !== "question") return;
    const timeMs = Math.min(performance.now() - startedAt.current, ROUND_LIMIT_MS);
    const correct = side !== null && side === current.answer;
    const out = applyRound(profileRef.current, current, correct, timeMs);
    dailyRounds.current.push({ correct, timeMs });
    profileRef.current = out.profile;
    phaseRef.current = "result";
    saveProfile(out.profile);
    setProfile(out.profile);
    setResult({ chosen: side, correct, timeMs, delta: out.delta, expected: out.expected, score: out.score });
    setPhase("result");
  }, []);

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
      else begin(profileRef.current, indexRef.current + 1);
      return;
    }
    begin(profileRef.current, 0);
  }, [begin, finishDaily, mode]);

  // Out of time counts as a miss.
  useEffect(() => {
    if (phase !== "question") return;
    const id = window.setTimeout(() => answer(null), ROUND_LIMIT_MS);
    return () => window.clearTimeout(id);
  }, [phase, runKey, answer]);

  const winChance = result ? result.expected : problem ? expectedScore(profile.rating, problem.rating) : null;
  const lastInSet = mode === "daily" && index + 1 >= DAILY_LENGTH;

  return { profile, problem, phase, result, runKey, winChance, answer, next, index, summary, lastInSet };
}
