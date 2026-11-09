import { useRef, useState } from "react";
import { api } from "../api/client";
import type { Timeseries } from "../api/types";
import { LineChart } from "../components/LineChart";
import { ErrorState, Loading, StaleNotice } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

const WINDOWS = [{ minutes: 15, label: "Last 15 min" }, { minutes: 60, label: "Last hour" }, { minutes: 360, label: "Last 6 hours" }];

export function Metrics() {
  const [windowMinutes, setWindowMinutes] = useState(60);
  const q = usePolling((s) => api.timeseries(windowMinutes, s), 15_000, () => true, [windowMinutes]);
  // While a new window loads, keep drawing the previous charts dimmed instead of flashing a skeleton.
  const last = useRef<Timeseries | null>(null);
  if (q.data) last.current = q.data;
  const shown = q.data ?? last.current;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Metrics</h1>
          <p className="muted">Live Prometheus queries for the demo shop, refreshed every 15 s. Fixed panels; the only choice here is the time window.</p>
        </div>
      </div>
      <div className="toolbar" role="group" aria-label="Time window">
        <div className="chips">{WINDOWS.map((w) => (
          <button key={w.minutes} className="chip" aria-pressed={windowMinutes === w.minutes} onClick={() => setWindowMinutes(w.minutes)}>{w.label}</button>))}</div>
        {shown && <span className="muted">Resolution {shown.step_s} s · as of {new Date(shown.generated_at).toLocaleTimeString()}</span>}
      </div>
      <StaleNotice stale={q.stale} lastUpdated={q.lastUpdated} />
      {!shown && q.loading ? <Loading what="metrics" /> : !shown && q.error ? <ErrorState error={q.error} onRetry={q.refresh} /> : shown && (
        <div className={`charts${q.loading ? " dim" : ""}`} aria-busy={q.loading}>
          {shown.panels.map((p) => <LineChart key={p.id} title={p.title} unit={p.unit} series={p.series.map((s) => ({ label: s.label, points: s.points }))} error={p.error} />)}
        </div>)}
    </>
  );
}
