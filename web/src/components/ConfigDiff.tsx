import { diffStrings, display, type Segment } from "../lib/diff";

interface Change { key: string; op: string; old?: unknown; new?: unknown }

function Side({ segments, kind }: { segments: Segment[]; kind: "removed" | "added" }) {
  return (
    <code className="diff-value">
      {segments.map((s, i) => s.changed
        ? <mark key={i} className={kind}><span className="sr-only">{kind === "removed" ? "removed: " : "added: "}</span>{s.text}</mark>
        : <span key={i}>{s.text}</span>)}
    </code>
  );
}

// Side-by-side view of proposed setting changes. Values are rendered as text; the highlighted part is the minimal
// differing span, and screen readers get "removed:" / "added:" before it so meaning never depends on colour.
export function ConfigDiff({ changes }: { changes: Change[] }) {
  if (!changes.length) return <p className="muted">No changes.</p>;
  return (
    <div className="diff" role="list" aria-label="Proposed setting changes">
      {changes.map((c) => {
        const d = diffStrings(c.op === "added" ? "" : display(c.old), c.op === "removed" ? "" : display(c.new));
        return (
          <div className="diff-row" role="listitem" key={c.key}>
            <div className="diff-key"><code>{c.key}</code> <span className="badge tone-muted">{c.op}</span></div>
            <div className="diff-cols">
              <div><div className="diff-head">Current (production)</div>
                {c.op === "added" ? <span className="muted">not set</span> : <Side segments={d.left} kind="removed" />}</div>
              <div aria-hidden="true" className="diff-arrow">→</div>
              <div><div className="diff-head">After (proposed)</div>
                {c.op === "removed" ? <span className="muted">removed</span> : <Side segments={d.right} kind="added" />}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
