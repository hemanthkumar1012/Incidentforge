export interface Segment { text: string; changed: boolean }
export interface StringDiff { left: Segment[]; right: Segment[] }

const BOUNDARY = new Set(["/", ":", ".", "-", "_", "?", "&", "=", "@", " ", ",", ";"]);
const isBoundary = (ch: string | undefined) => ch !== undefined && BOUNDARY.has(ch);

// Highlights what actually differs between two values by trimming the shared start and end. The cut points snap
// to separators (":", "/", ".", ...), so "http://payment:8020/x" vs "http://payment:8002/x" marks "8020" and
// "8002" as a whole instead of splitting a number or hostname in the middle.
export function diffStrings(a: string, b: string): StringDiff {
  if (a === b) return { left: [{ text: a, changed: false }], right: [{ text: b, changed: false }] };
  const limit = Math.min(a.length, b.length);

  let p = 0;
  while (p < limit && a[p] === b[p]) p++;
  while (p > 0 && !isBoundary(a[p - 1])) p--;

  let s = 0;
  while (s < limit - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
  while (s > 0 && !isBoundary(a[a.length - s])) s--;

  const split = (v: string): Segment[] =>
    [
      { text: v.slice(0, p), changed: false },
      { text: v.slice(p, v.length - s), changed: true },
      { text: v.slice(v.length - s), changed: false },
    ].filter((seg) => seg.text !== "");
  return { left: split(a), right: split(b) };
}

export function display(value: unknown): string {
  if (value === undefined || value === null) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}
