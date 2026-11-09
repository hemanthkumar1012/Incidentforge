import { NODE_H, NODE_W, layoutTopology } from "../lib/graph";

type Readiness = Record<string, { ready: boolean; status_code?: number; error?: string }>;

// Drawn from the live /api/system/overview topology and readiness. A service with no readiness
// record is drawn with a dashed outline and "unknown" rather than assumed healthy.
export function DependencyMap({ topology, services }: { topology: Record<string, string[]>; services: Readiness }) {
  const layout = layoutTopology(topology);
  if (!layout.nodes.length) return <p className="muted">No service topology reported.</p>;
  const at = new Map(layout.nodes.map((n) => [n.id, n]));
  const state = (id: string) => (services[id] ? (services[id]!.ready ? "ok" : "bad") : "unknown");
  const word = { ok: "ready", bad: "not ready", unknown: "unknown" } as const;
  const summary = layout.nodes.map((n) => `${n.id} ${word[state(n.id)]}`).join(", ");

  return (
    <svg className="depmap" viewBox={`0 0 ${layout.width} ${layout.height}`} role="img"
      aria-label={`Service dependency map. Arrows point from a service to what it depends on. ${summary}.`}>
      <defs>
        <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L8 4 L0 8 z" fill="var(--muted)" />
        </marker>
      </defs>
      {layout.edges.map((e) => {
        const a = at.get(e.from)!; const b = at.get(e.to)!;
        const x1 = a.x + NODE_W; const y1 = a.y + NODE_H / 2; const x2 = b.x; const y2 = b.y + NODE_H / 2;
        const mid = (x1 + x2) / 2;
        return <path key={`${e.from}>${e.to}`} className="edge" d={`M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2 - 2} ${y2}`} markerEnd="url(#arrow)" />;
      })}
      {layout.nodes.map((n) => (
        <g key={n.id} className={`node ${state(n.id)}`} transform={`translate(${n.x} ${n.y})`}>
          <rect width={NODE_W} height={NODE_H} />
          <text x={NODE_W / 2} y={20} textAnchor="middle" fontWeight="600">{n.id}</text>
          <text className="st" x={NODE_W / 2} y={35} textAnchor="middle">{word[state(n.id)]}</text>
        </g>
      ))}
    </svg>
  );
}
