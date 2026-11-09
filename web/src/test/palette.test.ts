import { describe, expect, it } from "vitest";
import { rankCommands, score, type Command } from "../lib/palette";

const cmd = (label: string, keywords?: string): Command => ({ id: label, label, group: "Go to", keywords, run: () => {} });

describe("command palette ranking", () => {
  const all = [cmd("Overview"), cmd("Incidents"), cmd("Approvals", "pending decisions"), cmd("Evaluation")];

  it("returns the first commands for an empty query", () => {
    expect(rankCommands(all, "  ").map((c) => c.label)).toEqual(["Overview", "Incidents", "Approvals", "Evaluation"]);
  });

  it("prefers prefix matches over scattered ones", () => {
    expect(rankCommands(all, "in")[0]!.label).toBe("Incidents");
  });

  it("matches a subsequence and hidden keywords", () => {
    expect(rankCommands(all, "ovw")[0]!.label).toBe("Overview");
    expect(rankCommands(all, "decisions")[0]!.label).toBe("Approvals");
  });

  it("drops commands that do not match", () => {
    expect(rankCommands(all, "zzz")).toEqual([]);
    expect(score("Overview", "xq")).toBeNull();
  });
});
