import type { Hypothesis } from "../api/types";

export interface HypNode { rank: number; label: string; y: number }
export interface EvNode { id: string; y: number; shared: boolean }
export interface Link { rank: number; evidenceId: string; kind: "supports" | "contradicts" }
export interface EvidenceGraph { hyps: HypNode[]; evidence: EvNode[]; links: Link[]; height: number }

export const ROW = 34;
const PAD = 10;

// Bipartite layout: hypotheses on the left, the evidence items they cite on the right.
// An evidence item cited by more than one hypothesis is marked "shared", which is where hypotheses compete
// over the same facts. Only IDs the hypotheses actually cite are drawn; nothing is inferred.
export function buildEvidenceGraph(hypotheses: Hypothesis[]): EvidenceGraph {
  const links: Link[] = hypotheses.flatMap((h) => [
    ...h.evidence_ids.map((evidenceId) => ({ rank: h.rank, evidenceId, kind: "supports" as const })),
    ...h.contradicting_evidence_ids.map((evidenceId) => ({ rank: h.rank, evidenceId, kind: "contradicts" as const })),
  ]);
  const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });
  const ids = Array.from(new Set(links.map((l) => l.evidenceId))).sort(natural);
  const uses = new Map<string, Set<number>>();
  for (const l of links) uses.set(l.evidenceId, (uses.get(l.evidenceId) ?? new Set()).add(l.rank));
  const hyps = hypotheses.map((h, i) => ({ rank: h.rank, label: `#${h.rank} ${h.component}`, y: PAD + i * ROW }));
  const evidence = ids.map((id, i) => ({ id, y: PAD + i * ROW, shared: (uses.get(id)?.size ?? 0) > 1 }));
  return { hyps, evidence, links, height: PAD * 2 + Math.max(hyps.length, evidence.length, 1) * ROW };
}
