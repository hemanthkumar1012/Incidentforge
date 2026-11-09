import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { Workspace } from "../../api/types";
import { useAuth } from "../../auth";
import { Badge, ConfirmDialog, Empty, ErrorState, Loading, StaleNotice, Time } from "../../components/ui";
import { usePolling } from "../../hooks/usePolling";
import { ActionPanel } from "./ActionPanel";
import { InvestigationView } from "./InvestigationView";

const BUSY = new Set(["queued", "running", "validating", "requested", "executing", "verifying"]);

function inFlight(w: Workspace | null): boolean {
  if (!w) return true;
  return w.investigations.some((i) => BUSY.has(i.status)) || w.proposals.some((p) => BUSY.has(p.status))
    || w.validations.some((v) => BUSY.has(v.status)) || w.recoveries.some((r) => BUSY.has(r.status))
    || w.approvals.some((a) => a.status === "pending");
}

export function IncidentWorkspace() {
  const { id = "" } = useParams();
  // Poll fast while something is running, slowly otherwise (an approver may act from elsewhere).
  const [fast, setFast] = useState(true);
  const q = usePolling(async (s) => { const w = await api.workspace(id, s); setFast(inFlight(w)); return w; },
                       fast ? 2_500 : 10_000, () => true, [id, fast]);
  if (q.loading) return <Loading what="incident" />;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refresh} />;
  const w = q.data!;
  const latest = w.investigations[0];
  const proposal = w.proposals[0];

  return (
    <>
      <IncidentHeader w={w} onChange={q.refresh} />
      <StaleNotice stale={q.stale} lastUpdated={q.lastUpdated} />
      <div className="workspace">
        <div>{latest ? <InvestigationView key={latest.id} investigation={latest} /> :
          <Empty>No investigation yet. Start one to collect metrics, logs, traces and config changes.</Empty>}</div>
        <div>
          {proposal ? <ActionPanel proposal={proposal} onChange={q.refresh}
            validation={w.validations.find((v) => v.proposal_id === proposal.id)}
            approval={w.approvals.find((a) => a.proposal_id === proposal.id)}
            recovery={w.recoveries.find((r) => r.proposal_id === proposal.id)} /> :
            <section className="card"><h2>Proposed repair</h2><p className="muted">{latest?.diagnosis?.outcome === "diagnosed"
              ? "No allowlisted action fits this diagnosis; escalate to a human responder (see the timeline for the planner's reason)."
              : "A repair is proposed only after an evidence-backed diagnosis."}</p></section>}
          <AuditTrail id={w.incident.id} />
        </div>
      </div>
    </>
  );
}

function IncidentHeader({ w, onChange }: { w: Workspace; onChange: () => void }) {
  const { can } = useAuth();
  const [mode, setMode] = useState("");
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const i = w.incident;
  const running = w.investigations.some((x) => BUSY.has(x.status));
  async function start() {
    setError(null);
    try { await api.startInvestigation(i.id, mode || undefined); onChange(); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
  }
  async function close() {
    try { await api.closeIncident(i.id, "closed from workspace"); setClosing(false); onChange(); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); setClosing(false); }
  }
  const affected = w.investigations[0]?.diagnosis?.affected ?? [];
  return (
    <header className="card">
      <div className="header-row"><h1>{i.title}</h1><Badge value={i.severity} /><Badge value={i.status} /></div>
      <p className="muted">Opened <Time iso={i.created_at} /> by {i.created_by} ({i.source}) · updated <Time iso={i.updated_at} />
        {i.resolved_at && <> · resolved <Time iso={i.resolved_at} /></>}{i.synthetic_traffic && " · synthetic traffic"}</p>
      {affected.length > 0 && <p><strong>Affected:</strong> {affected.join(", ")}</p>}
      {!["resolved", "closed"].includes(i.status) && (
        <div className="toolbar">
          {can("investigation:run") && <>
            <div className="field"><label htmlFor="mode">Investigation mode</label>
              <select id="mode" value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="">server default</option><option value="runbook">runbook (no LLM)</option>
                <option value="llm">LLM with tools (Gemini)</option><option value="llm_summary">LLM fixed summary (baseline)</option></select></div>
            <button className="primary" onClick={start} disabled={running}>{running ? "Investigation running…" : w.investigations.length ? "Re-investigate" : "Start investigation"}</button></>}
          {can("incident:close") && <button onClick={() => setClosing(true)}>Close incident…</button>}
        </div>)}
      {error && <p className="field-error" role="alert">{error}</p>}
      <ConfirmDialog open={closing} title="Close this incident without a verified repair?" confirmLabel="Close incident"
        onCancel={() => setClosing(false)} onConfirm={close}><p>The incident is closed (not resolved) and the closure is recorded in the audit history.</p></ConfirmDialog>
    </header>
  );
}

function AuditTrail({ id }: { id: string }) {
  const q = usePolling((s) => api.timeline(id, s), 5_000, () => true, [id]);
  return (
    <section className="card" aria-labelledby="audit-h">
      <h2 id="audit-h">Audit history</h2>
      {q.error && !q.data ? <ErrorState error={q.error} /> : !q.data ? <Loading what="audit history" /> : (
        <ol className="timeline">{q.data.items.map((e) => (
          <li key={e.id}><strong>{e.action}</strong> by {e.actor}<div className="muted" style={{ fontSize: 12 }}><Time iso={e.occurred_at} /></div></li>))}</ol>)}
    </section>
  );
}
