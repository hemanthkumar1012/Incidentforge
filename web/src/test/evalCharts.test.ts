import { describe, expect, it } from "vitest";
import { buildMetrics, parseRatio } from "../lib/evalCharts";

describe("evaluation charts", () => {
  it("parses printed ratios and refuses to invent a rate for 0/0", () => {
    expect(parseRatio("3/5")).toEqual({ num: 3, den: 5, pct: 60 });
    expect(parseRatio("0/0")).toEqual({ num: 0, den: 0, pct: null });
    expect(parseRatio("n/a")).toBeNull();
  });

  it("labels each bar with the counts behind the percentage", () => {
    const m = buildMetrics([{ mode: "runbook", top1: "3/3", median_latency_s: 2 }, { mode: "llm", top1: "1/3", median_latency_s: 8 }]);
    const top1 = m.find((x) => x.key === "top1")!;
    expect(top1.bars.map((b) => b.label)).toEqual(["3/3 (100%)", "1/3 (33%)"]);
    const lat = m.find((x) => x.key === "median_latency_s")!;
    expect(lat.bars.map((b) => b.widthPct)).toEqual([25, 100]);
  });

  it("shows missing values as no data, not zero", () => {
    const m = buildMetrics([{ mode: "runbook", top1: "0/0", median_latency_s: null }]);
    expect(m.find((x) => x.key === "top1")!.bars[0]).toMatchObject({ label: "0/0", missing: true });
    expect(m.find((x) => x.key === "median_latency_s")!.bars[0]).toMatchObject({ label: "no data", missing: true });
  });
});
