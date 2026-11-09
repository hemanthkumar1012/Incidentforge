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
      {shown && <Events t={shown} />}
      {!shown && q.loading ? <Loading what="metrics" /> : !shown && q.error ? <ErrorState error={q.error} onRetry={q.refresh} /> : shown && (
        <div className={`charts${q.loading ? " dim" : ""}`} aria-busy={q.loading}>
          {shown.panels.map((p) => <LineChart key={p.id} title={p.title} unit={p.unit} series={p.series.map((s) => ({ label: s.label, points: s.points }))}
            error={p.error} annotations={shown.annotations} range={range(shown)} />)}
        </div>)}
    </>
  );
}

// The window the server queried, as unix seconds, so event markers use the same axis as the data.
function range(t: Timeseries): [number, number] {
  const end = Date.parse(t.generated_at) / 1000;
  return [end - t.window_minutes * 60, end];
}

function Events({ t }: { t: Timeseries }) {
  if (t.annotations_error) return <p className="stale" role="status">Event markers unavailable: {t.annotations_error}</p>;
  if (!t.annotations.length) return <p className="muted">No configuration changes or new incidents in this window.</p>;
  return (
    <section className="card" aria-labelledby="ev-list-h">
      <h2 id="ev-list-h">Events in this window</h2>
      <ul className="event-list">{t.annotations.map((a) => (
        <li key={`${a.kind}-${a.ref}`}><span className={`event-key ${a.kind}`} aria-hidden="true">{a.kind === "incident" ? "!" : "Δ"}</span>
          <time dateTime={new Date(a.ts * 1000).toISOString()}>{new Date(a.ts * 1000).toLocaleTimeString()}</time> {a.label}</li>))}
      </ul>
      <p className="muted" style={{ fontSize: 12 }}>Δ is a checkout configuration change; ! is an incident opening. The same markers appear on every chart.</p>
    </section>
  );
}
