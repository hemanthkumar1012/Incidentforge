export type CountdownState = "ok" | "soon" | "expired";
export interface Countdown { remainingMs: number; label: string; state: CountdownState; fractionLeft: number }

const SOON_MS = 3 * 60_000;

function format(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}:${String(s).padStart(2, "0")}`;
}

// Display-only. This uses the browser clock, which may differ from the server's; the server alone decides whether an
// approval is still valid, and re-checks at execution time. So "expired" here is a hint, never an authorisation.
export function countdown(requestedAt: string, expiresAt: string, now: number): Countdown | null {
  const start = Date.parse(requestedAt);
  const end = Date.parse(expiresAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  const remainingMs = end - now;
  if (remainingMs <= 0) return { remainingMs: 0, label: "expired", state: "expired", fractionLeft: 0 };
  return {
    remainingMs, label: `${format(remainingMs)} left`, state: remainingMs <= SOON_MS ? "soon" : "ok",
    fractionLeft: Math.min(1, remainingMs / (end - start)),
  };
}
