import { describe, expect, it } from "vitest";
import type { Evidence } from "../api/types";
import { buildWaterfall } from "../lib/timing";

const ev = (id: string, createdAt: string, durationMs: number, ok = true): Evidence => ({
  id, tool: "query_metrics", arguments: {}, ok, data: null, error: null, summary: "", injection_flags: [],
  truncated: false, duration_ms: durationMs, created_at: createdAt, trust: "untrusted",
});

describe("buildWaterfall", () => {
  it("places each bar so it ends at the time the evidence was recorded", () => {
    const w = buildWaterfall([ev("E1", "2026-01-01T00:00:01.000Z", 500), ev("E2", "2026-01-01T00:00:03.000Z", 1000)]);
    expect(w.spanMs).toBe(2500);
    expect(w.rows.map((r) => [r.id, r.startMs])).toEqual([["E1", 0], ["E2", 1500]]);
  });

  it("keeps instant calls visible and handles no evidence", () => {
    const w = buildWaterfall([ev("E1", "2026-01-01T00:00:01.000Z", 0), ev("E2", "2026-01-01T00:00:02.000Z", 0)]);
    expect(w.rows.every((r) => r.widthPct > 0)).toBe(true);
    expect(buildWaterfall([])).toEqual({ rows: [], spanMs: 0 });
  });

  it("ignores records with an unparseable timestamp", () => {
    expect(buildWaterfall([ev("E1", "not a date", 10)]).rows).toEqual([]);
  });
});
