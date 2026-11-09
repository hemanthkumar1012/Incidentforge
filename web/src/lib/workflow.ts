import type { Workspace } from "../api/types";

export type StageState = "done" | "current" | "failed" | "todo";
export interface Stage { key: string; label: string; state: StageState }

const BAD_INVESTIGATION = new Set(["failed", "cancelled", "insufficient_evidence", "budget_exhausted"]);
const BAD_VALIDATION = new Set(["failed", "not_reproducible", "error"]);
const BAD_APPROVAL = new Set(["rejected", "expired", "invalidated"]);
const BAD_RECOVERY = new Set(["verification_failed", "refused", "rolled_back", "failed"]);

// Derives the response stages from records the API returned. Nothing here is assumed: a stage is "done"
// only when the matching record says so, and an unsuccessful end state is shown as "failed", not skipped.
export function deriveStages(w: Workspace): Stage[] {
  const inv = w.investigations[0];
  const proposal = w.proposals[0];
  const validation = proposal ? w.validations.find((v) => v.proposal_id === proposal.id) : undefined;
  const approval = proposal ? w.approvals.find((a) => a.proposal_id === proposal.id) : undefined;
  const recovery = proposal ? w.recoveries.find((r) => r.proposal_id === proposal.id) : undefined;

  const stages: Stage[] = [
    { key: "detected", label: "Detected", state: "done" },
    { key: "investigated", label: "Investigated", state: !inv ? "todo" : inv.status === "completed" ? "done"
      : BAD_INVESTIGATION.has(inv.status) ? "failed" : "current" },
    { key: "proposed", label: "Repair proposed", state: proposal ? "done" : "todo" },
    { key: "validated", label: "Validated in sandbox", state: !validation ? "todo" : validation.status === "passed" ? "done"
      : BAD_VALIDATION.has(validation.status) ? "failed" : "current" },
    { key: "approved", label: "Approved", state: !approval ? "todo" : ["approved", "consumed"].includes(approval.status) ? "done"
      : BAD_APPROVAL.has(approval.status) ? "failed" : "current" },
    { key: "executed", label: "Executed", state: !recovery ? "todo" : BAD_RECOVERY.has(recovery.status) ? "failed"
      : ["succeeded", "verifying"].includes(recovery.status) ? "done" : "current" },
    { key: "verified", label: "Verified", state: !recovery ? "todo" : recovery.status === "succeeded" ? "done"
      : BAD_RECOVERY.has(recovery.status) ? "failed" : "todo" },
  ];

  // If nothing is in progress or failed, the next stage that has not started is the one the responder should act on.
  const active = stages.some((s) => s.state === "current" || s.state === "failed");
  if (!active) {
    const next = stages.find((s) => s.state === "todo");
    if (next && !["resolved", "closed"].includes(w.incident.status)) next.state = "current";
  }
  return stages;
}
