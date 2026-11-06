/** Phase 4 backend access. Nothing here runs unless sync is enabled (see SYNC_ENABLED). */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");
/** With sync off the app behaves exactly as before Phase 4: everything stays in this browser. */
export const SYNC_ENABLED = process.env.NEXT_PUBLIC_SYNC === "on" && API_URL !== "";

export type ApiErrorKind =
  /** No connection, DNS failure or timeout: try again later */
  | "offline"
  /** 401: the token is not known to the server */
  | "unauthorized"
  /** 409, 429, 5xx: the server is there but can't take this right now */
  | "retryable"
  /** Any other 4xx: retrying the same request won't help */
  | "fatal";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface Options {
  method?: "GET" | "POST";
  body?: unknown;
  token?: string;
  /** Lets the request outlive the page (used when the tab is closing). Bodies must stay under 64 KB. */
  keepalive?: boolean;
  timeoutMs?: number;
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 408 || status === 409 || status === 425 || status === 429 || status >= 500) return "retryable";
  return "fatal";
}

export async function apiFetch<T>(path: string, { method = "GET", body, token, keepalive, timeoutMs = 10_000 }: Options = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      keepalive,
      signal: controller.signal,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new ApiError("offline", err instanceof Error ? err.message : "network error");
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      /* not JSON */
    }
    throw new ApiError(kindFor(res.status), `${res.status} ${detail}`, res.status);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("retryable", "the server sent a response that isn't JSON", res.status);
  }
}
