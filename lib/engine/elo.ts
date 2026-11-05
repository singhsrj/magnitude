/**
 * Elo with a speed-adjusted outcome.
 *
 * Instead of win/lose, each round yields a score in [0, 1]:
 *   wrong or timed out  -> 0
 *   correct, very slow  -> 0.70
 *   correct, very fast  -> 1.00
 * Elo accepts fractional outcomes, so accuracy and fluency collapse into one number.
 */
export const DEFAULT_RATING = 1200;
export const K_FACTOR = 24;
export const TIME_FAST_MS = 800;
export const TIME_SLOW_MS = 6000;
export const ROUND_LIMIT_MS = 8000;
/** The game aims to serve problems you'd "win" this often */
export const TARGET_WIN_RATE = 0.7;

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export function expectedScore(player: number, problem: number): number {
  return 1 / (1 + Math.pow(10, (problem - player) / 400));
}

export function outcomeScore(correct: boolean, timeMs: number): number {
  if (!correct) return 0;
  const speed = clamp((TIME_SLOW_MS - timeMs) / (TIME_SLOW_MS - TIME_FAST_MS), 0, 1);
  return 0.7 + 0.3 * speed;
}

/** Problem rating at which the player's expected score equals `targetWin`. */
export function targetProblemRating(player: number, targetWin = TARGET_WIN_RATE): number {
  return player + 400 * Math.log10((1 - targetWin) / targetWin);
}

export interface EloUpdate {
  next: number;
  delta: number;
  expected: number;
  score: number;
}

export function updatePlayer(player: number, problem: number, correct: boolean, timeMs: number): EloUpdate {
  const expected = expectedScore(player, problem);
  const score = outcomeScore(correct, timeMs);
  const delta = K_FACTOR * (score - expected);
  return { next: player + delta, delta, expected, score };
}
