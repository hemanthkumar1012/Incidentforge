export interface PlacedNode { id: string; layer: number; row: number; x: number; y: number }
export interface Edge { from: string; to: string }
export interface Layout { nodes: PlacedNode[]; edges: Edge[]; width: number; height: number }

export const NODE_W = 132;
export const NODE_H = 46;
const COL_GAP = 70;
const ROW_GAP = 22;
const PAD = 8;

// Layered left-to-right layout: a service sits one column to the left of the services it depends on.
// The layer is the longest dependency chain below the node. The pass count is capped at the node count,
// so a cycle in the topology cannot loop forever; it just stops lengthening chains.
export function layoutTopology(topology: Record<string, string[]>): Layout {
  const ids = Array.from(new Set([...Object.keys(topology), ...Object.values(topology).flat()])).sort();
  const edges: Edge[] = ids.flatMap((from) => (topology[from] ?? []).map((to) => ({ from, to })));

  const depth = new Map<string, number>(ids.map((id) => [id, 0]));
  for (let pass = 0; pass < ids.length; pass++) {
    let changed = false;
    for (const e of edges) {
      const want = (depth.get(e.to) ?? 0) + 1;
      if (want > (depth.get(e.from) ?? 0) && want < ids.length) { depth.set(e.from, want); changed = true; }
    }
    if (!changed) break;
  }

  // Callers on the left: invert so the deepest dependency chain starts at column 0.
  const maxDepth = Math.max(0, ...depth.values());
  const columns = new Map<number, string[]>();
  for (const id of ids) {
    const layer = maxDepth - (depth.get(id) ?? 0);
    columns.set(layer, [...(columns.get(layer) ?? []), id]);
  }
  const nodes: PlacedNode[] = [];
  for (const [layer, members] of columns) {
    members.forEach((id, row) => nodes.push({ id, layer, row, x: PAD + layer * (NODE_W + COL_GAP), y: PAD + row * (NODE_H + ROW_GAP) }));
  }
  const tallest = Math.max(1, ...[...columns.values()].map((c) => c.length));
  return {
    nodes, edges,
    width: PAD * 2 + (maxDepth + 1) * NODE_W + maxDepth * COL_GAP,
    height: PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP,
  };
}
