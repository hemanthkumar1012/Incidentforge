export type RawPoint = [number, number | null];
export interface SeriesIn { label: string; points: RawPoint[] }

// Series colour follows the entity, not its rank: slots are assigned by sorted label, so a series keeps its
// colour when a refresh reorders them or another series appears. Slots wrap after the 8 validated hues, but the
// API caps a panel at 8 series.
export const SERIES_SLOTS = 8;
export function colorSlots(labels: string[]): Map<string, number> {
  const sorted = [...new Set(labels)].sort((a, b) => a.localeCompare(b));
  return new Map(sorted.map((label, i) => [label, i % SERIES_SLOTS]));
}

// Round a maximum up to 1, 2 or 5 times a power of ten so the y axis ends on a tidy value.
export function niceCeil(max: number): number {
  if (!Number.isFinite(max) || max <= 0) return 1;
  const exp = Math.floor(Math.log10(max));
  const base = 10 ** exp;
  const f = max / base;
  const step = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return step * base;
}

export function yTicks(top: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, i) => (top * i) / count);
}

// One SVG path per series. A gap (null) ends the current segment, so missing data is shown as a break, never
// interpolated across. An isolated point becomes a zero-length segment so it still draws as a dot with round caps.
export function linePath(points: RawPoint[], x: (t: number) => number, y: (v: number) => number): string {
  const parts: string[] = [];
  let run: [number, number][] = [];
  const flush = () => {
    if (run.length === 1) parts.push(`M${run[0]![0]} ${run[0]![1]}h0`);
    else if (run.length > 1) parts.push(`M${run.map(([px, py]) => `${px} ${py}`).join("L")}`);
    run = [];
  };
  for (const [t, v] of points) {
    if (v === null) flush();
    else run.push([round(x(t)), round(y(v))]);
  }
  flush();
  return parts.join("");
}

const round = (n: number) => Math.round(n * 10) / 10;

export function nearestIndex(times: number[], t: number): number {
  if (!times.length) return -1;
  let best = 0;
  for (let i = 1; i < times.length; i++) if (Math.abs(times[i]! - t) < Math.abs(times[best]! - t)) best = i;
  return best;
}

export function formatValue(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return "no data";
  if (unit === "s" && Math.abs(v) < 1) return `${trim(v * 1000)} ms`;
  return `${trim(v)}${unit ? ` ${unit}` : ""}`;
}

function trim(n: number): string {
  if (n === 0) return "0";
  const abs = Math.abs(n);
  return abs >= 100 ? n.toFixed(0) : abs >= 10 ? n.toFixed(1) : abs >= 1 ? n.toFixed(2) : n.toPrecision(2);
}

// Distinct sorted timestamps across all series: the positions the crosshair can snap to.
export function allTimes(series: SeriesIn[]): number[] {
  return [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
}

// End-of-line labels: keep each at its line's last value but nudge downward so labels never overlap.
export function spreadLabels(ys: number[], minGap: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  let prev = -Infinity;
  const out = [...ys];
  for (const o of order) { const y = Math.max(o.y, prev + minGap); out[o.i] = y; prev = y; }
  return out;
}
