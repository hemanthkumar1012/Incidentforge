import { describe, expect, it } from "vitest";
import { allTimes, colorSlots, formatValue, linePath, nearestIndex, niceCeil, spreadLabels, yTicks } from "../lib/chart";

const id = (n: number) => n;

describe("chart math", () => {
  it("rounds the axis maximum up to a tidy value", () => {
    expect([niceCeil(0), niceCeil(0.7), niceCeil(1.2), niceCeil(3), niceCeil(7), niceCeil(130), niceCeil(NaN)]).toEqual([1, 1, 2, 5, 10, 200, 1]);
    expect(yTicks(10, 2)).toEqual([0, 5, 10]);
  });

  it("keeps a series colour tied to its label, not its position", () => {
    const a = colorSlots(["payment", "checkout", "inventory"]);
    const b = colorSlots(["inventory", "payment"]);
    expect(a.get("checkout")).toBe(0);
    expect(a.get("payment")).toBe(2);
    expect(b.get("payment")).toBe(1); // alphabetical among the series present; stable for the same set
  });

  it("breaks the line at gaps instead of interpolating", () => {
    expect(linePath([[0, 1], [1, 2], [2, null], [3, 4], [4, 5]], id, id)).toBe("M0 1L1 2M3 4L4 5");
  });

  it("draws an isolated point as a dot and empty input as nothing", () => {
    expect(linePath([[0, null], [1, 3], [2, null]], id, id)).toBe("M1 3h0");
    expect(linePath([], id, id)).toBe("");
  });

  it("finds the nearest timestamp and merges times across series", () => {
    expect(nearestIndex([10, 20, 30], 26)).toBe(2);
    expect(nearestIndex([], 5)).toBe(-1);
    expect(allTimes([{ label: "a", points: [[2, 1], [1, 1]] }, { label: "b", points: [[2, 1], [3, 1]] }])).toEqual([1, 2, 3]);
  });

  it("formats values with units and says so when there is no data", () => {
    expect(formatValue(0.0123, "s")).toBe("12.3 ms");
    expect(formatValue(2.5, "req/s")).toBe("2.50 req/s");
    expect(formatValue(null, "s")).toBe("no data");
    expect(formatValue(0, "orders/s")).toBe("0 orders/s");
  });

  it("spreads overlapping end labels apart", () => {
    expect(spreadLabels([10, 11, 12], 12)).toEqual([10, 22, 34]);
    expect(spreadLabels([50, 10], 12)).toEqual([50, 10]);
  });
});
