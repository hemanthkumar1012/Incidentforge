import { useState } from "react";
import { ApiError, api } from "../../api/client";
import type { Approval, Proposal, RecoveryJob, ValidationRun } from "../../api/types";
import { useAuth } from "../../auth";
import { ConfigDiff } from "../../components/ConfigDiff";
import { ExpiryMeter } from "../../components/ExpiryMeter";
import { Badge, ChangeTable, ConfirmDialog, Time } from "../../components/ui";

interface Props {
  proposal: Proposal; validation: ValidationRun | undefined; approval: Approval | undefined;
  recovery: RecoveryJob | undefined; onChange: () => void;
}

// Proposal → validation → approval → execution → verification, in one column.
// Every button maps to one API call; state shown is whatever the API returns next.
export function ActionPanel({ proposal, validation, approval, recovery, onChange }: Props) {
  const { can, me } = useAuth();
  const [confirm, setConfirm] = useState<null | "validate" | "approval" | "execute">(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); setConfirm(null); onChange(); }
    catch (err) { setError(err instanceof ApiError ? `${err.message}${err.details.reasons ? ` (${(err.details.reasons as string[]).join("; ")})` : ""}` : String(err)); }
    finally { setBusy(false); }
  }

  const validated = proposal.status === "validated" && validation?.status === "passed";
  const approved = approval?.status === "approved";
  return (
    <section className="card" aria-labelledby="act-h">
      <h2 id="act-h">Proposed repair</h2>
      <div className="header-row"><code>{proposal.action_type}</code> on <strong>{proposal.target}</strong><Badge value={proposal.status} /></div>
      <p>{proposal.rationale}</p>
      <ConfigDiff changes={proposal.expected_effect ?? []} />
      {!!proposal.side_effects?.length && <><h3>Also changes (side effects)</h3><ConfigDiff changes={proposal.side_effects} /></>}
      <details><summary>Preconditions, validation and rollback procedure</summary>
        <h3>Preconditions</h3><ul>{proposal.preconditions?.map((p) => <li key={p}>{p}</li>)}</ul>
        <h3>Validation procedure</h3><ol>{proposal.validation_procedure?.map((p) => <li key={p}>{p}</li>)}</ol>
        <h3>Rollback</h3><p>{proposal.rollback_procedure?.description}</p>
        <p className="muted">Approval: {proposal.approval_requirement} · Evidence: {proposal.evidence_ids?.join(", ")}</p>
      </details>

      <h3>1 · Isolated validation</h3>
      {!validation ? <p className="muted">Not validated. An unvalidated proposal cannot be approved.</p> : <ValidationResult run={validation} />}
      {can("proposal:validate") && ["proposed", "validated", "validation_failed", "not_reproducible"].includes(proposal.status) &&
        <button onClick={() => setConfirm("validate")} disabled={busy}>{validation ? "Re-validate" : "Validate in sandbox"}</button>}

      <h3>2 · Approval</h3>
      {approval ? <ApprovalSummary approval={approval} /> : <p className="muted">{validated ? "Approval required before execution." : "Available after validation passes."}</p>}
      {validated && can("approval:request") && (!approval || ["rejected", "expired", "invalidated"].includes(approval.status)) &&
        <button onClick={() => setConfirm("approval")} disabled={busy}>Request approval</button>}
      {approval?.status === "pending" && can("approval:decide") && approval.requested_by !== me?.username && <DecisionButtons approval={approval} onDone={onChange} />}
      {approval?.status === "pending" && approval.requested_by === me?.username && <p className="muted">Waiting for a different approver; you requested this action.</p>}

      <h3>3 · Execution and verification</h3>
      {recovery ? <RecoveryOutcome job={recovery} /> : <p className="muted">{approved ? "Approved and ready to execute." : "Not executed. A proposal is not a repair until it runs and is verified."}</p>}
      {approved && !recovery && can("recovery:execute") && <button className="danger" onClick={() => setConfirm("execute")} disabled={busy}>Execute approved action</button>}
      {error && <p className="field-error" role="alert">{error}</p>}

      <ConfirmDialog open={confirm === "validate"} title="Validate in the sandbox?" confirmLabel="Start validation" busy={busy}
        onCancel={() => setConfirm(null)} onConfirm={() => run(() => api.requestValidation(proposal.id))}>
        <p>Copies the active production config (v{proposal.expected_active_version}) into the isolated sandbox, checks that checkout fails there, applies <code>{JSON.stringify(proposal.parameters)}</code> and runs recovery and regression checks. Production is not touched. Any open approval for this proposal is invalidated.</p>
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "approval"} title="Request approval for this exact action?" confirmLabel="Request approval" busy={busy}
        onCancel={() => setConfirm(null)} onConfirm={() => run(() => api.requestApproval(proposal.id))}>
        <ExactAction proposal={proposal} />
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "execute"} title="Change production?" confirmLabel="Execute on production" danger busy={busy}
        onCancel={() => setConfirm(null)} onConfirm={() => run(() => api.requestRecovery(proposal.id))}>
        <ExactAction proposal={proposal} />
        <p>Refused automatically if production config is no longer v{proposal.expected_active_version}. Recovery is then verified with synthetic checkouts.</p>
      </ConfirmDialog>
    </section>
  );
}

function ExactAction({ proposal }: { proposal: Proposal }) {
  return (<>
    <p><code>{proposal.action_type}</code> on <strong>{proposal.target}</strong> with <code>{JSON.stringify(proposal.parameters)}</code>, replacing config v{proposal.expected_active_version}:</p>
    <ChangeTable changes={[...(proposal.expected_effect ?? []), ...(proposal.side_effects ?? [])]} />
  </>);
}

function ValidationResult({ run }: { run: ValidationRun }) {
  const messages: Record<string, string> = {
    passed: "Reproduced in the sandbox, repaired, no regressions.",
    failed: "Validation failed: the repair did not fix the sandbox or caused a regression. Execution is blocked.",
    not_reproducible: "The failure did not reproduce in the sandbox, so the repair is NOT verified. Execution is blocked.",
    error: "The sandbox was unusable for this run; nothing was verified.",
    queued: "Queued…", running: "Running in the sandbox…",
  };
  return (
    <div>
      <p><Badge value={run.status} /> {messages[run.status]} <span className="muted">(<Time iso={run.finished_at ?? run.created_at} />)</span></p>
      {run.report.steps?.filter((s) => s.checks).map((s) => (
        <div key={s.phase}><strong>{s.phase}</strong> <span className="muted">(expect {s.expect})</span>
          <ul className="step-list">{s.checks!.map((c) => <li key={c.name}><Badge value={c.passed ? "passed" : "failed"} label={c.passed ? "pass" : "fail"} /><code>{c.name}</code><span className="muted">{c.detail}</span></li>)}</ul></div>))}
      {!!run.report.uncertainty?.length && <details><summary>Uncertainty</summary><ul>{run.report.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul></details>}
    </div>
  );
}

function ApprovalSummary({ approval }: { approval: Approval }) {
  const notes: Record<string, string> = {
    pending: "Approval required.", rejected: "Rejected; request a new approval to proceed.",
    expired: "Expired before a decision; request a new approval.", invalidated: "Stale: the proposal was re-validated or production changed. Request a new approval.",
    approved: "Approved for this exact action.", consumed: "Used by the execution below.",
  };
  return <p><Badge value={approval.status} /> {notes[approval.status]} <span className="muted">Requested by {approval.requested_by}{approval.decided_by && `, decided by ${approval.decided_by}`} · expires <Time iso={approval.expires_at} /></span>{approval.status === "pending" && <> <ExpiryMeter requestedAt={approval.requested_at} expiresAt={approval.expires_at} /></>}</p>;
}

export function DecisionButtons({ approval, onDone }: { approval: Approval; onDone: () => void }) {
  const [mode, setMode] = useState<null | "approve" | "reject">(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function decide() {
    if (note.trim().length < 3) { setError("Add a short note (at least 3 characters) explaining the decision."); return; }
    setBusy(true); setError(null);
    try { await api.decide(approval.id, mode === "approve", note.trim(), approval.binding_digest); setMode(null); onDone(); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  return (<>
    <div className="header-row"><button className="primary" onClick={() => setMode("approve")}>Approve…</button><button onClick={() => setMode("reject")}>Reject…</button></div>
    <ConfirmDialog open={mode !== null} title={mode === "approve" ? "Approve this exact action?" : "Reject this action?"}
      confirmLabel={mode === "approve" ? "Approve" : "Reject"} danger={mode === "reject"} busy={busy}
      onCancel={() => { setMode(null); setError(null); }} onConfirm={decide}>
      <p><code>{String(approval.binding.action_type)}</code> on <strong>{String(approval.binding.target)}</strong> with <code>{JSON.stringify(approval.binding.parameters)}</code>, expecting production config v{String(approval.binding.expected_active_version)}, validated by run <code>{approval.validation_run_id}</code>.</p>
      <p className="muted" style={{ fontSize: 13 }}>Digest <code>{approval.binding_digest}</code>. The server refuses the decision if the action changed after you opened this.</p>
      <div className="field"><label htmlFor="note">Decision note</label><textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} aria-invalid={!!error} /></div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </ConfirmDialog>
  </>);
}

export function RecoveryOutcome({ job }: { job: RecoveryJob }) {
  const v = job.result.verification;
  const text: Record<string, string> = {
    requested: "Queued for execution…", executing: "Applying the change…", verifying: "Change applied; verifying with synthetic checkouts…",
    succeeded: "Recovery verified: synthetic checkouts succeed after the change.",
    verification_failed: "Change applied but recovery is NOT verified: checkouts still fail. Use the rollback procedure via a new approval.",
    refused: "Refused before any change: preconditions no longer held.", failed: "Execution failed.",
  };
  return (
    <div aria-live="polite">
      <p><Badge value={job.status} /> {text[job.status] ?? job.status}</p>
      {job.config_version_before !== null && <p className="muted">Config v{job.config_version_before} → v{job.config_version_after} · <Time iso={job.finished_at} /></p>}
      {job.result.reasons && <ul>{job.result.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
      {v && <ul className="step-list">{v.checks.map((c) => <li key={c.name}><Badge value={c.passed ? "passed" : "failed"} label={c.passed ? "pass" : "fail"} /><code>{c.name}</code>{c.status !== undefined && <span className="muted">HTTP {c.status}</span>}</li>)}</ul>}
    </div>
  );
}
