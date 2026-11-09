import type { AuditEvent, Workspace } from "../api/types";

// Titles, summaries and component names can contain text that came from the monitored system.
// Escape characters that would turn it into markup or break a table when the report is rendered elsewhere.
export function md(text: unknown): string {
  return String(text ?? "").replace(/[\\`*_{}[\]<>|#]/g, "\\$&").replace(/\r?\n/g, " ");
}

const iso = (v: string | null | undefined) => (v ? v : "n/a");

// Plain-text incident report assembled only from records the API returned. Raw evidence payloads are left out on
// purpose (they are untrusted system output); evidence is referenced by ID so a reader can open it in the app.
export function buildReport(w: Workspace, audit: AuditEvent[] = [], generatedAt = new Date()): string {
  const i = w.incident;
  const inv = w.investigations[0];
  const proposal = w.proposals[0];
  const validation = proposal ? w.validations.find((v) => v.proposal_id === proposal.id) : undefined;
  const approval = proposal ? w.approvals.find((a) => a.proposal_id === proposal.id) : undefined;
  const recovery = proposal ? w.recoveries.find((r) => r.proposal_id === proposal.id) : undefined;
  const out: string[] = [];

  out.push(`# Incident report: ${md(i.title)}`, "");
  out.push(`- Incident ID: ${i.id}`, `- Severity: ${i.severity}`, `- Status: ${i.status}`, `- Source: ${i.source}`,
    `- Opened: ${iso(i.created_at)} by ${md(i.created_by)}`, `- Resolved: ${iso(i.resolved_at)}`,
    `- Report generated: ${generatedAt.toISOString()} (a snapshot; the application is the source of truth)`, "");

  out.push("## Investigation", "");
  if (!inv) out.push("No investigation has been run.", "");
  else {
    out.push(`- Mode: ${inv.mode} (${md(inv.provider)}${inv.model !== "none" ? ` / ${md(inv.model)}` : ""})`, `- Status: ${inv.status}`,
      `- Tool calls: ${inv.usage.tool_calls ?? 0}`, "");
    const d = inv.diagnosis;
    if (!d) out.push("No diagnosis recorded.", "");
    else if (d.outcome !== "diagnosed") {
      out.push(`Outcome: ${d.outcome.replaceAll("_", " ")}. The investigator did not name a root cause.`, "");
      d.limitations.forEach((l) => out.push(`- Limitation: ${md(l)}`));
      if (d.limitations.length) out.push("");
    } else {
      out.push("### Hypotheses", "");
      d.hypotheses.forEach((h) => {
        out.push(`${h.rank}. **${md(h.category.replaceAll("_", " "))}** in ${md(h.component)} (${h.confidence} confidence): ${md(h.summary)}`);
        out.push(`   - Supported by: ${h.evidence_ids.join(", ") || "none"}`);
        if (h.contradicting_evidence_ids.length) out.push(`   - Contradicted by: ${h.contradicting_evidence_ids.join(", ")}`);
      });
      out.push("");
    }
  }

  out.push("## Repair", "");
  if (!proposal) out.push("No repair was proposed.", "");
  else {
    out.push(`- Action: ${proposal.action_type} on ${md(proposal.target)} (status: ${proposal.status})`);
    (proposal.expected_effect ?? []).forEach((c) => out.push(`  - ${md(c.key)}: ${md(c.old ?? "unset")} -> ${md(c.new ?? "unset")}`));
    out.push(`- Sandbox validation: ${validation ? `${validation.status}${validation.report.verdict ? ` (${md(validation.report.verdict)})` : ""}` : "not requested"}`);
    out.push(`- Approval: ${approval ? `${approval.status}, requested by ${md(approval.requested_by)}${approval.decided_by ? `, decided by ${md(approval.decided_by)}` : ""}` : "not requested"}`);
    out.push(`- Production execution: ${recovery ? recovery.status : "not run"}`);
    if (recovery) {
      const v = recovery.result.verification;
      out.push(`- Post-change verification: ${v ? (v.passed ? "passed" : "FAILED") : "not recorded"}`);
    }
    out.push("");
  }

  if (audit.length) {
    out.push("## Audit history (oldest first)", "");
    [...audit].sort((a, b) => a.id - b.id).forEach((e) => out.push(`- ${e.occurred_at} ${md(e.actor)}: ${md(e.action)}`));
    out.push("");
  }
  return out.join("\n");
}

export function downloadText(filename: string, mime: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
