import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Annotation } from "../api/types";
import { allTimes, colorSlots, formatValue, linePath, nearestIndex, niceCeil, spreadLabels, yTicks, type SeriesIn } from "../lib/chart";

const W = 640;
const H = 230;
const M = { l: 54, r: 104, t: 12, b: 28 };
const PLOT_W = W - M.l - M.r;
const PLOT_H = H - M.t - M.b;
const DIRECT_LABEL_MAX = 4;
const TABLE_ROWS = 40;

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

// Line chart drawn in SVG. Labels and series names come from the API and are only ever rendered as text.
// Reachable without a pointer: arrow keys move the readout, and a table view lists the same values.
export function LineChart({ title, unit, series, error, annotations = [], range }: {
  title: string; unit: string; series: SeriesIn[]; error: string | null;
  annotations?: Annotation[]; range?: [number, number];   // range = the query window, so event markers line up with the axis
}) {
  const uid = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [active, setActive] = useState<number | null>(null);

  const slots = useMemo(() => colorSlots(series.map((s) => s.label)), [series]);
  const visible = series.filter((s) => !hidden.has(s.label));
  const times = useMemo(() => allTimes(series), [series]);
  const tMin = range?.[0] ?? times[0] ?? 0;
  const tMax = range?.[1] ?? times[times.length - 1] ?? 1;
  const events = annotations.filter((a) => a.ts >= tMin && a.ts <= tMax);
  const peak = Math.max(0, ...visible.flatMap((s) => s.points.map((p) => p[1] ?? 0)));
  const top = niceCeil(peak);
  const x = (t: number) => M.l + (tMax === tMin ? PLOT_W / 2 : ((t - tMin) / (tMax - tMin)) * PLOT_W);
  const y = (v: number) => M.t + PLOT_H - (v / top) * PLOT_H;
  const color = (label: string) => `var(--series-${(slots.get(label) ?? 0) + 1})`;

  const toggle = (label: string) => setHidden((h) => { const n = new Set(h); if (n.has(label)) n.delete(label); else n.add(label); return n; });

  function pointerTime(e: PointerEvent<SVGRectElement>): number {
    const box = svgRef.current!.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    return tMin + ((px - M.l) / PLOT_W) * (tMax - tMin);
  }
  function onKey(e: KeyboardEvent<SVGRectElement>) {
    if (!times.length) return;
    const i = active ?? times.length - 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); setActive(Math.max(0, i - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setActive(Math.min(times.length - 1, i + 1)); }
    else if (e.key === "Escape") setActive(null);
  }

  const readout = active !== null && times[active] !== undefined ? times[active]! : null;
  const rows = readout === null ? [] : visible.map((s) => ({ label: s.label, value: s.points.find((p) => p[0] === readout)?.[1] ?? null }));
  const direct = visible.length <= DIRECT_LABEL_MAX && visible.length > 0
    ? (() => {
        const lasts = visible.map((s) => { const last = [...s.points].reverse().find((p) => p[1] !== null); return last ? y(last[1]!) : null; });
        const placed = spreadLabels(lasts.map((v) => v ?? M.t), 13);
        return visible.map((s, i) => ({ label: s.label, y: placed[i]!, show: lasts[i] !== null }));
      })()
    : [];

  return (
    <figure className="linechart" aria-labelledby={`${uid}-t`}>
      <figcaption id={`${uid}-t`}><strong>{title}</strong> <span className="muted">· {unit}</span></figcaption>
      {error ? <p className="state failed" role="alert">{error}</p> : series.length === 0 ? (
        <p className="muted state">No samples in this window. The panel is empty when the shop has had no matching traffic.</p>
      ) : (
        <>
          {series.length >= 2 && (
            <ul className="legend" aria-label={`${title} series`}>
              {series.map((s) => (
                <li key={s.label}><button aria-pressed={!hidden.has(s.label)} onClick={() => toggle(s.label)} title="Show or hide this series">
                  <span className="legend-key" style={{ background: color(s.label) }} aria-hidden="true" />{s.label}</button></li>
              ))}
            </ul>)}
          <div className="chart-wrap">
            <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="group" aria-label={`${title}, line chart`}>
              {yTicks(top).map((v) => (
                <g key={v}><line className="grid" x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} />
                  <text className="tick" x={M.l - 8} y={y(v) + 4} textAnchor="end">{formatValue(v, "").trim()}</text></g>
              ))}
              {[0, 1 / 3, 2 / 3, 1].map((f) => (
                <text key={f} className="tick" x={M.l + f * PLOT_W} y={H - 8} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"}>{clock(tMin + f * (tMax - tMin))}</text>
              ))}
              {visible.map((s) => <path key={s.label} className="series-line" d={linePath(s.points, x, y)} stroke={color(s.label)} />)}
              {events.map((a) => (
                <g key={`${a.kind}-${a.ref}`} className={`event ${a.kind}`}>
                  <title>{`${new Date(a.ts * 1000).toLocaleTimeString()} · ${a.label}`}</title>
                  <line x1={x(a.ts)} x2={x(a.ts)} y1={M.t + 12} y2={M.t + PLOT_H} />
                  <circle cx={x(a.ts)} cy={M.t + 6} r="7" /><text x={x(a.ts)} y={M.t + 10} textAnchor="middle">{a.kind === "incident" ? "!" : "Δ"}</text>
                </g>))}
              {direct.filter((d) => d.show).map((d) => <text key={d.label} className="direct" x={W - M.r + 8} y={d.y + 4}>{d.label}</text>)}
              {readout !== null && <line className="crosshair" x1={x(readout)} x2={x(readout)} y1={M.t} y2={M.t + PLOT_H} />}
              {readout !== null && visible.map((s) => {
                const v = s.points.find((p) => p[0] === readout)?.[1];
                return v === null || v === undefined ? null : <circle key={s.label} className="dot" cx={x(readout)} cy={y(v)} r="4" fill={color(s.label)} />;
              })}
              <rect className="hit" x={M.l} y={M.t} width={PLOT_W} height={PLOT_H} tabIndex={0} aria-label={`${title}. Use left and right arrow keys to read values.`}
                onPointerMove={(e) => times.length && setActive(nearestIndex(times, pointerTime(e)))} onPointerLeave={() => setActive(null)}
                onKeyDown={onKey} onBlur={() => setActive(null)} />
            </svg>
            {readout !== null && (
              <div className="chart-tip" role="status" style={{ left: `${(x(readout) / W) * 100}%`, transform: x(readout) > W * 0.6 ? "translateX(calc(-100% - 12px))" : "translateX(12px)" }}>
                <div className="tip-time">{new Date(readout * 1000).toLocaleTimeString()}</div>
                {rows.map((r) => (
                  <div key={r.label} className="tip-row"><span className="legend-line" style={{ background: color(r.label) }} aria-hidden="true" />
                    <strong>{formatValue(r.value, unit)}</strong> <span className="muted">{r.label}</span></div>
                ))}
              </div>)}
          </div>
          <details className="chart-table"><summary>Show values as a table</summary>
            <div className="table-wrap"><table className="table compact">
              <thead><tr><th scope="col">Time</th>{visible.map((s) => <th key={s.label} scope="col">{s.label}</th>)}</tr></thead>
              <tbody>{times.slice(-TABLE_ROWS).map((t) => (
                <tr key={t}><td>{new Date(t * 1000).toLocaleTimeString()}</td>
                  {visible.map((s) => <td key={s.label}>{formatValue(s.points.find((p) => p[0] === t)?.[1] ?? null, unit)}</td>)}</tr>
              ))}</tbody>
            </table></div>
            {times.length > TABLE_ROWS && <p className="muted">Showing the latest {TABLE_ROWS} of {times.length} samples.</p>}
          </details>
        </>)}
    </figure>
  );
}
