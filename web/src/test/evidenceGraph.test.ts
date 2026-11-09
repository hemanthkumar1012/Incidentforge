import { describe, expect, it } from "vitest";
import type { Hypothesis } from "../api/types";
import { buildEvidenceGraph } from "../lib/evidenceGraph";

const hyp = (rank: number, support: string[], against: string[] = []): Hypothesis => ({
  rank, category: "bad_config", component: `svc${rank}`, faulty_setting: null, summary: "", confidence: "medium",
  evidence_ids: support, contradicting_evidence_ids: against,
});

describe("buildEvidenceGraph", () => {
  it("draws only cited evidence, once, in natural order", () => {
    const g = buildEvidenceGraph([hyp(1, ["E10", "E2"]), hyp(2, ["E2"], ["E1"])]);
    expect(g.evidence.map((e) => e.id)).toEqual(["E1", "E2", "E10"]);
    expect(g.links).toHaveLength(4);
  });

  it("marks evidence shared between hypotheses and keeps contradictions distinct", () => {
    const g = buildEvidenceGraph([hyp(1, ["E1"]), hyp(2, [], ["E1"])]);
    expect(g.evidence[0]!.shared).toBe(true);
    expect(g.links.map((l) => l.kind)).toEqual(["supports", "contradicts"]);
  });

  it("copes with no hypotheses", () => {
    expect(buildEvidenceGraph([])).toMatchObject({ hyps: [], evidence: [], links: [] });
  });
});
