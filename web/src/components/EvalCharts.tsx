import { buildMetrics, type SummaryRow } from "../lib/evalCharts";

// Bars for one evaluation run. Every bar carries its raw value as text, so the chart is never the only
// place a number appears, and a mode with no data is labelled instead of drawn as zero.
export function EvalCharts({ rows }: { rows: SummaryRow[] }) {
  const metrics = buildMetrics(rows);
  if (!metrics.length) return null;
  return (
    <div className="eval-charts">
      {metrics.map((m) => (
        <figure key={m.key} className="eval-chart" aria-label={m.title}>
          <figcaption>{m.title}</figcaption>
          {m.bars.map((b) => (
            <div key={b.mode} className="eval-row">
              <span className="eval-mode">{b.mode}</span>
              <span className="eval-track" aria-hidden="true"><span className={`eval-fill${b.missing ? " missing" : ""}`} style={{ width: `${b.widthPct}%` }} /></span>
              <span className="eval-val">{b.label}</span>
            </div>
          ))}
        </figure>
      ))}
    </div>
  );
}
