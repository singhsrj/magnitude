import {
  DAILY_LENGTH,
  applyRound,
  dateKey,
  recordDaily,
  type Problem,
  type Profile,
} from "./engine";
import type { OutboxEvent } from "./syncTypes";

/**
 * The local profile after the server's verdict: the server's profile, with every round that hasn't been
 * acknowledged yet applied on top. Pure (no storage, no network), so it is easy to test.
 *
 * Normally the result equals what the player already sees, because both sides run the same engine.
 * When it doesn't (a rejected round, play on another device) the server's view wins.
 */
export function reconcileProfile(server: Profile, pending: readonly OutboxEvent[]): Profile {
  let profile = server;
  const dailyByDate = new Map<string, OutboxEvent[]>();

  for (const ev of pending) {
    // applyRound only reads the problem's skill and rating
    const problem = { skill: ev.skill, rating: ev.problemRating } as Problem;
    profile = applyRound(profile, problem, ev.correct, ev.timeMs, ev.at).profile;
    if (ev.kind === "daily") dailyByDate.set(ev.date, [...(dailyByDate.get(ev.date) ?? []), ev]);
  }

  // A daily set finished while its rounds were still unsynced: show it as done now. Only when every one of
  // its rounds is pending, so the numbers are complete; otherwise the server's result arrives with the sync.
  for (const [date, events] of dailyByDate) {
    if (events.length === DAILY_LENGTH && !profile.daily[date]) {
      profile = recordDaily(profile, date, {
        correct: events.filter((e) => e.correct).length,
        total: events.length,
        timeMs: events.reduce((sum, e) => sum + e.timeMs, 0),
      });
    }
  }
  return profile;
}

/** Body for `POST /v1/players` carrying a pre-Phase-4 browser profile (accepted once, unverified). */
export function profileToImport(profile: Profile) {
  const newestFirst = (a: string, b: string) => (a < b ? 1 : -1);
  const keep = <T,>(record: Record<string, T>) =>
    Object.fromEntries(Object.entries(record).sort(([a], [b]) => newestFirst(a, b)).slice(0, 400));
  return {
    rating: profile.rating,
    peak: profile.peak,
    skills: profile.skills,
    streak: profile.streak,
    bestStreak: profile.bestStreak,
    rounds: profile.rounds,
    history: profile.history.slice(-200).map((h) => ({ ...h, localDate: dateKey(h.at) })),
    days: keep(profile.days),
    daily: keep(profile.daily),
  };
}
