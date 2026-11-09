import { describe, expect, it } from "vitest";
import type { Workspace } from "../api/types";
import { deriveStages } from "../lib/workflow";

const empty = { incident: { status: "open" }, investigations: [], proposals: [], validations: [], approvals: [], recoveries: [] };
const ws = (over: Record<string, unknown>) => ({ ...empty, ...over }) as unknown as Workspace;
const states = (w: Workspace) => Object.fromEntries(deriveStages(w).map((s) => [s.key, s.state]));
const proposal = { id: "p1" };

describe("deriveStages", () => {
  it("marks the first unstarted stage as the next one for a fresh incident", () => {
    expect(states(ws({}))).toMatchObject({ detected: "done", investigated: "current", proposed: "todo" });
  });

  it("shows a validation that could not reproduce the fault as failed, not done", () => {
    const w = ws({ investigations: [{ status: "completed" }], proposals: [proposal],
      validations: [{ proposal_id: "p1", status: "not_reproducible" }] });
    expect(states(w)).toMatchObject({ proposed: "done", validated: "failed", approved: "todo" });
  });

  it("does not report verified until the recovery succeeded", () => {
    const base = { investigations: [{ status: "completed" }], proposals: [proposal],
      validations: [{ proposal_id: "p1", status: "passed" }], approvals: [{ proposal_id: "p1", status: "consumed" }] };
    expect(states(ws({ ...base, recoveries: [{ proposal_id: "p1", status: "verifying" }] }))).toMatchObject({ executed: "done", verified: "todo" });
    expect(states(ws({ ...base, recoveries: [{ proposal_id: "p1", status: "verification_failed" }] }))).toMatchObject({ executed: "failed", verified: "failed" });
    expect(states(ws({ ...base, recoveries: [{ proposal_id: "p1", status: "succeeded" }] }))).toMatchObject({ verified: "done" });
  });

  it("leaves no stage marked current once the incident is resolved", () => {
    const w = ws({ incident: { status: "resolved" }, investigations: [{ status: "completed" }], proposals: [proposal],
      validations: [{ proposal_id: "p1", status: "passed" }], approvals: [{ proposal_id: "p1", status: "consumed" }],
      recoveries: [{ proposal_id: "p1", status: "succeeded" }] });
    expect(deriveStages(w).every((s) => s.state === "done")).toBe(true);
  });
});
