import { describe, expect, it } from "vitest";
import { diffStrings, display } from "../lib/diff";

const marked = (segs: { text: string; changed: boolean }[]) => segs.filter((s) => s.changed).map((s) => s.text);

describe("diffStrings", () => {
  it("marks only the differing port in a URL", () => {
    const d = diffStrings("http://payment:8020/charge", "http://payment:8002/charge");
    expect(marked(d.left)).toEqual(["8020"]);
    expect(marked(d.right)).toEqual(["8002"]);
    expect(d.left.map((s) => s.text).join("")).toBe("http://payment:8020/charge");
  });

  it("marks a changed hostname as a whole", () => {
    const d = diffStrings("http://payment:8020", "http://sandbox-payment:8020");
    expect(marked(d.left)).toEqual(["payment"]);
    expect(marked(d.right)).toEqual(["sandbox-payment"]);
  });

  it("returns an unchanged value as one unmarked segment", () => {
    expect(diffStrings("same", "same")).toEqual({ left: [{ text: "same", changed: false }], right: [{ text: "same", changed: false }] });
  });

  it("marks everything when nothing is shared, and handles an empty side", () => {
    expect(marked(diffStrings("abc", "xyz").left)).toEqual(["abc"]);
    expect(marked(diffStrings("", "x").right)).toEqual(["x"]);
  });

  it("never loses or duplicates characters", () => {
    for (const [a, b] of [["a.b.c", "a.x.c"], ["30", "3"], ["retry=3", "retry=30"], ["x", "xx"]] as const) {
      const d = diffStrings(a, b);
      expect(d.left.map((s) => s.text).join("")).toBe(a);
      expect(d.right.map((s) => s.text).join("")).toBe(b);
    }
  });
});

describe("display", () => {
  it("shows missing values as a dash and objects as JSON", () => {
    expect(display(undefined)).toBe("—");
    expect(display(null)).toBe("—");
    expect(display({ a: 1 })).toBe('{"a":1}');
    expect(display(30)).toBe("30");
  });
});
