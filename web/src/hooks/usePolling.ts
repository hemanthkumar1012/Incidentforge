import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface Polled<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  stale: boolean;          // last refresh failed; data shown is from an earlier successful fetch
  lastUpdated: Date | null;
  refresh: () => void;
}

// Fetches immediately, then every `intervalMs` while `active(data)` is true.
// - Each fetch gets its own AbortController; unmount or a newer fetch cancels it.
// - Failures back off exponentially (×2, capped at 30 s) and keep the last good data
//   visible but flagged `stale`, instead of blanking the screen or inventing data.
// - Polling pauses while the tab is hidden and resumes on focus.
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, intervalMs: number,
                              active: (data: T | null) => boolean = () => true, deps: unknown[] = []): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [tick, setTick] = useState(0);
  const failures = useRef(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let latest: T | null = null;
    const run = async () => {
      if (document.hidden) { timer = setTimeout(run, intervalMs); return; }
      try {
        latest = await fetcher(controller.signal);
        failures.current = 0;
        setData(latest); setError(null); setLastUpdated(new Date());
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        failures.current += 1;
        setError(err instanceof ApiError ? err : new ApiError(0, "client_error", String(err)));
        if (err instanceof ApiError && (err.isAuth || err.isForbidden || err.status === 404)) { setLoading(false); return; }
      } finally {
        setLoading(false);
      }
      if (active(latest)) {
        const delay = failures.current ? Math.min(intervalMs * 2 ** failures.current, 30_000) : intervalMs;
        timer = setTimeout(run, delay);
      }
    };
    void run();
    return () => { controller.abort(); clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, intervalMs, ...deps]);

  return { data, error, loading, stale: error !== null && data !== null, lastUpdated, refresh };
}
