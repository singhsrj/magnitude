const pad = (n: number) => String(n).padStart(2, "0");

/** Local calendar date as "YYYY-MM-DD". The streak and daily set follow the player's own day. */
export function dateKey(at: Date | number = new Date()): string {
  const d = typeof at === "number" ? new Date(at) : at;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function addDays(key: string, n: number): string {
  const [y, m, d] = key.split("-").map(Number);
  return dateKey(new Date(y, m - 1, d + n));
}

/** The last `n` date keys ending at `today`, oldest first. */
export function lastDays(n: number, today: string = dateKey()): string[] {
  return Array.from({ length: n }, (_, i) => addDays(today, i - (n - 1)));
}
