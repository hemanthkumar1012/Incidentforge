import { describe, expect, it } from "vitest";
import { countdown } from "../lib/countdown";

const t0 = Date.parse("2026-01-01T00:00:00Z");
const at = (min: number) => new Date(t0 + min * 60_000).toISOString();

describe("countdown", () => {
  it("reports time left and the fraction of the window remaining", () => {
    const c = countdown(at(0), at(15), t0 + 5 * 60_000)!;
    expect(c.label).toBe("10:00 left");
    expect(c.state).toBe("ok");
    expect(c.fractionLeft).toBeCloseTo(10 / 15);
  });

  it("flags the last few minutes and then expiry", () => {
    expect(countdown(at(0), at(15), t0 + 13 * 60_000)!.state).toBe("soon");
    expect(countdown(at(0), at(15), t0 + 15 * 60_000)).toMatchObject({ state: "expired", label: "expired", fractionLeft: 0 });
  });

  it("returns null for unusable timestamps", () => {
    expect(countdown("nope", at(15), t0)).toBeNull();
    expect(countdown(at(15), at(0), t0)).toBeNull();
  });
});
