import { describe, expect, it } from "vitest";
import { layoutTopology } from "../lib/graph";

const col = (l: ReturnType<typeof layoutTopology>, id: string) => l.nodes.find((n) => n.id === id)!.layer;

describe("layoutTopology", () => {
  it("places callers to the left of their dependencies", () => {
    const l = layoutTopology({ checkout: ["payment", "inventory"], payment: [], inventory: [] });
    expect(col(l, "checkout")).toBeLessThan(col(l, "payment"));
    expect(col(l, "payment")).toBe(col(l, "inventory"));
    expect(l.edges).toHaveLength(2);
  });

  it("includes services that only appear as dependencies", () => {
    expect(layoutTopology({ checkout: ["payment"] }).nodes.map((n) => n.id).sort()).toEqual(["checkout", "payment"]);
  });

  it("terminates on a cyclic topology", () => {
    const l = layoutTopology({ a: ["b"], b: ["a"] });
    expect(l.nodes).toHaveLength(2);
  });

  it("handles an empty topology", () => {
    expect(layoutTopology({}).nodes).toEqual([]);
  });
});
