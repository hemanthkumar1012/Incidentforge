import type { Evidence } from "../api/types";
import { buildWaterfall } from "../lib/timing";

const fmt = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`);

// Tool-call waterfall built from the recorded evidence. Each row is a button that opens that evidence.
export function Waterfall({ evidence, onSelect }: { evidence: Evidence[]; onSelect: (id: string) => void }) {
  const { rows, spanMs } = buildWaterfall(evidence);
  if (!rows.length) return null;
  return (
    <section aria-labelledby="wf-h">
      <h3 id="wf-h">Tool-call waterfall <span className="muted">· total {fmt(spanMs)}</span></h3>
      <ul className="waterfall">
        {rows.map((r) => (
          <li key={r.id}>
            <button className="wf-label" onClick={() => onSelect(r.id)} title={`Open ${r.id}`}><strong>{r.id}</strong> <code>{r.tool}</code></button>
            <span className="wf-track" aria-hidden="true">
              <span className={`wf-bar${r.ok ? "" : " bad"}`} style={{ left: `${r.leftPct}%`, width: `${r.widthPct}%` }} />
            </span>
            <span className="wf-time">{fmt(r.durationMs)}{!r.ok && <span className="flag"> failed</span>}</span>
          </li>
        ))}
      </ul>
      <p className="muted" style={{ fontSize: 12 }}>Each bar ends when the result was recorded and spans the tool call's duration.</p>
    </section>
  );
}
