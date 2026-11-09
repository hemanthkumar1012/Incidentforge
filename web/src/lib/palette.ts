export interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;       // secondary text, e.g. a shortcut or an incident status
  keywords?: string;   // extra words that should match but are not displayed
  run: () => void;
}

// Subsequence match ("ovw" finds "Overview") with a score that prefers prefix and word-start hits.
// Returns null when the query does not match, so callers can drop the command.
export function score(text: string, query: string): number | null {
  const t = text.toLowerCase();
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const direct = t.indexOf(q);
  if (direct >= 0) return 1000 - direct * 10 - (t.length - q.length) + (direct === 0 || t[direct - 1] === " " ? 200 : 0);
  let pos = 0;
  let gaps = 0;
  for (const ch of q) {
    const next = t.indexOf(ch, pos);
    if (next < 0) return null;
    gaps += next - pos;
    pos = next + 1;
  }
  return 500 - gaps;
}

export function rankCommands(commands: Command[], query: string, limit = 12): Command[] {
  if (!query.trim()) return commands.slice(0, limit);
  return commands
    .map((c) => ({ c, s: score(`${c.label} ${c.keywords ?? ""}`, query) }))
    .filter((x): x is { c: Command; s: number } => x.s !== null)
    .sort((a, b) => b.s - a.s)
    .slice(0, limit)
    .map((x) => x.c);
}
