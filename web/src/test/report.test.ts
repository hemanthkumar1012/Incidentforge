import { describe, expect, it } from "vitest";
import type { Workspace } from "../api/types";
import { buildReport, md } from "../lib/report";

const base = {
  incident: { id: "i1", title: "Checkout <b>down</b> | 5xx", status: "open", severity: "sev1", source: "detector",
    created_by: "detector", created_at: "2026-01-01T00:00:00Z", resolved_at: null },
  investigations: [], proposals: [], validations: [], approvals: [], recoveries: [],
} as unknown as Workspace;

describe("incident report", () => {
  it("escapes markup that came from titles", () => {
    expect(md("a <b> | `c`")).toBe("a \\<b\\> \\| \\`c\\`");
    expect(buildReport(base)).toContain("# Incident report: Checkout \\<b\\>down\\</b\\> \\| 5xx");
  });

  it("states plainly when nothing was investigated or proposed", () => {
    const r = buildReport(base);
    expect(r).toContain("No investigation has been run.");
    expect(r).toContain("No repair was proposed.");
  });

  it("does not claim verification without a recovery record", () => {
    const w = { ...base, proposals: [{ id: "p1", action_type: "config_rollback", target: "checkout", status: "validated", expected_effect: [] }] } as unknown as Workspace;
    const r = buildReport(w);
    expect(r).toContain("Production execution: not run");
    expect(r).not.toContain("Post-change verification");
  });

  it("reports a failed verification as FAILED", () => {
    const w = { ...base, proposals: [{ id: "p1", action_type: "config_rollback", target: "checkout", status: "executed" }],
      recoveries: [{ proposal_id: "p1", status: "verification_failed", result: { verification: { passed: false, checks: [] } } }] } as unknown as Workspace;
    expect(buildReport(w)).toContain("Post-change verification: FAILED");
  });
});
