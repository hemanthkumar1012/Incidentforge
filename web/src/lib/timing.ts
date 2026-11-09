import type { Evidence } from "../api/types";

export interface WaterfallRow { id: string; tool: string; ok: boolean; startMs: number; durationMs: number; leftPct: number; widthPct: number }
export interface Waterfall { rows: WaterfallRow[]; spanMs: number }

const MIN_WIDTH_PCT = 0.8;   // keeps very fast calls visible

// Evidence is stored when a tool call returns, so each bar ends at the record's created_at and starts
// duration_ms earlier. Rows are relative to the earliest start; nothing is estimated beyond that.
export function buildWaterfall(evidence: Evidence[]): Waterfall {
  const timed = evidence
    .map((e) => ({ e, end: Date.parse(e.created_at), dur: Math.max(0, e.duration_ms) }))
    .filter((x) => Number.isFinite(x.end));
  if (!timed.length) return { rows: [], spanMs: 0 };
  const origin = Math.min(...timed.map((x) => x.end - x.dur));
  const spanMs = Math.max(1, Math.max(...timed.map((x) => x.end)) - origin);
  const rows = timed
    .map(({ e, end, dur }) => {
      const startMs = end - dur - origin;
      return {
        id: e.id, tool: e.tool, ok: e.ok, startMs, durationMs: dur,
        leftPct: (startMs / spanMs) * 100, widthPct: Math.max(MIN_WIDTH_PCT, (dur / spanMs) * 100),
      };
    })
    .sort((a, b) => a.startMs - b.startMs);
  return { rows, spanMs };
}
