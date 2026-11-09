export type SummaryRow = Record<string, string | number | null>;
export interface Ratio { num: number; den: number; pct: number | null }
export interface Bar { mode: string; label: string; widthPct: number; missing: boolean }
export interface Metric { key: string; title: string; kind: "ratio" | "scalar"; unit: string; bars: Bar[] }

// "3/5" -> 3 of 5. A zero denominator has no rate, so pct is null (shown as "no data", never as 0%).
export function parseRatio(v: unknown): Ratio | null {
  const m = /^(\d+)\s*\/\s*(\d+)$/.exec(String(v ?? "").trim());
  if (!m) return null;
  const num = Number(m[1]);
  const den = Number(m[2]);
  return { num, den, pct: den > 0 ? (num / den) * 100 : null };
}

const RATIOS: [string, string][] = [["top1", "Top-1 correct"], ["top3", "Top-3 correct"], ["recovered", "Recovery succeeded"]];
const SCALARS: [string, string, string][] = [["median_latency_s", "Median investigation latency", "s"], ["mean_tool_calls", "Mean tool calls", ""]];

// Turns the summary rows written by `lab evaluate` into bars. Values are copied from the results file; the only
// arithmetic is the percentage for a printed ratio and scaling scalar bars to the largest value shown.
export function buildMetrics(rows: SummaryRow[]): Metric[] {
  const metrics: Metric[] = [];
  for (const [key, title] of RATIOS) {
    if (!rows.some((r) => key in r)) continue;
    metrics.push({ key, title, kind: "ratio", unit: "", bars: rows.map((r) => {
      const ratio = parseRatio(r[key]);
      return { mode: String(r.mode), label: ratio ? `${ratio.num}/${ratio.den}${ratio.pct === null ? "" : ` (${Math.round(ratio.pct)}%)`}` : "no data",
        widthPct: ratio?.pct ?? 0, missing: !ratio || ratio.pct === null };
    }) });
  }
  for (const [key, title, unit] of SCALARS) {
    if (!rows.some((r) => key in r)) continue;
    const values = rows.map((r) => (typeof r[key] === "number" ? (r[key] as number) : null));
    const max = Math.max(0, ...values.filter((v): v is number => v !== null));
    metrics.push({ key, title, kind: "scalar", unit, bars: rows.map((r, i) => {
      const v = values[i] ?? null;
      return { mode: String(r.mode), label: v === null ? "no data" : `${v}${unit ? ` ${unit}` : ""}`, widthPct: v !== null && max > 0 ? (v / max) * 100 : 0, missing: v === null };
    }) });
  }
  return metrics;
}
