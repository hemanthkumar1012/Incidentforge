import type { Evidence, Hypothesis } from "../api/types";
import { ROW, buildEvidenceGraph } from "../lib/evidenceGraph";

const W = 560;
const NODE_W = 170;

export function EvidenceGraph({ hypotheses, evidence, onSelect }: {
  hypotheses: Hypothesis[]; evidence: Evidence[]; onSelect: (id: string) => void;
}) {
  const g = buildEvidenceGraph(hypotheses);
  if (!g.links.length) return null;
  const byId = new Map(evidence.map((e) => [e.id, e]));
  const hy = new Map(g.hyps.map((h) => [h.rank, h]));
  const ev = new Map(g.evidence.map((e) => [e.id, e]));
  return (
    <section aria-labelledby="eg-h">
      <h3 id="eg-h">How hypotheses use the evidence</h3>
      <svg className="egraph" viewBox={`0 0 ${W} ${g.height}`} role="group" aria-label="Links between hypotheses and the evidence they cite">
        {g.links.map((l) => {
          const a = hy.get(l.rank)!; const b = ev.get(l.evidenceId)!;
          const x1 = NODE_W; const y1 = a.y + ROW / 2 - 4; const x2 = W - NODE_W; const y2 = b.y + ROW / 2 - 4; const mid = W / 2;
          return <path key={`${l.rank}-${l.evidenceId}-${l.kind}`} className={`link ${l.kind}`} d={`M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`} />;
        })}
        {g.hyps.map((h) => (
          <g key={h.rank} className="gnode" transform={`translate(0 ${h.y})`}><rect width={NODE_W} height={ROW - 8} rx="6" />
            <text x="10" y="17">{h.label.length > 24 ? `${h.label.slice(0, 23)}…` : h.label}</text></g>
        ))}
        {g.evidence.map((e) => {
          const rec = byId.get(e.id);
          return (
            <g key={e.id} className={`gnode ev${rec && !rec.ok ? " failed" : ""}${e.shared ? " shared" : ""}`} transform={`translate(${W - NODE_W} ${e.y})`}
              tabIndex={0} role="button" aria-label={`Evidence ${e.id}${rec ? ` ${rec.tool}, ${rec.ok ? "ok" : "failed"}` : ""}${e.shared ? ", cited by several hypotheses" : ""}`}
              onClick={() => onSelect(e.id)} onKeyDown={(k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); onSelect(e.id); } }}>
              <rect width={NODE_W} height={ROW - 8} rx="6" /><text x="10" y="17">{e.id} {rec?.tool ?? ""}</text></g>
          );
        })}
      </svg>
      <p className="muted" style={{ fontSize: 12 }}>
        Solid lines support a hypothesis; dashed red lines contradict it. A thick outline marks evidence cited by more than one hypothesis.
      </p>
    </section>
  );
}
