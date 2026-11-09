import { useState } from "react";
import { api } from "../../api/client";
import type { Evidence, Investigation, InvestigationDetail } from "../../api/types";
import { Badge, ErrorState, Loading, StaleNotice, Time, UntrustedBlock } from "../../components/ui";
import { Waterfall } from "../../components/Waterfall";
import { usePolling } from "../../hooks/usePolling";

const RUNNING = new Set(["queued", "running"]);
const MODE_LABEL: Record<string, string> = {
  runbook: "Runbook (deterministic rules, no LLM)", llm: "LLM investigator with tools", llm_summary: "LLM with fixed summary (baseline)",
};

// `view` lets the workspace put the analysis and the raw evidence on separate tabs; the default shows both.
export type InvestigationViewMode = "all" | "analysis" | "evidence";

export function InvestigationView({ investigation, view = "all", onCite }: {
  investigation: Investigation; view?: InvestigationViewMode; onCite?: () => void;
}) {
  const q = usePolling((s) => api.investigation(investigation.id, s), 2_000,
                       (d) => !d || RUNNING.has(d.status), [investigation.id]);
  const [focused, setFocused] = useState<string | null>(null);
  const cite = (id: string) => { setFocused(id); onCite?.(); };
  if (q.loading) return <Loading what="investigation" />;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refresh} />;
  const inv = q.data as InvestigationDetail;

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr)" }}>
      {view !== "evidence" && <section className="card" aria-labelledby="inv-h">
        <div className="header-row">
          <h2 id="inv-h" style={{ margin: 0 }}>Investigation</h2><Badge value={inv.status} />
          <span className="muted">{MODE_LABEL[inv.mode] ?? inv.mode} · {inv.provider}{inv.model !== "none" && ` / ${inv.model}`}</span>
        </div>
        <StaleNotice stale={q.stale} lastUpdated={q.lastUpdated} />
        <p className="muted">Started <Time iso={inv.started_at} /> · finished <Time iso={inv.finished_at} /> ·
          {" "}{inv.usage.tool_calls ?? 0} tool calls{inv.usage.total_tokens ? ` · ${inv.usage.total_tokens} tokens` : ""}</p>
        {RUNNING.has(inv.status) && <p role="status">Investigation {inv.status}… the timeline updates as evidence is collected.</p>}
        {inv.status === "failed" && <p className="state failed" role="alert">Investigation failed: {inv.failure_reason}</p>}
        {inv.status === "budget_exhausted" && <p className="state denied">Budget exhausted before a conclusion: {inv.failure_reason}</p>}
        <Diagnosis inv={inv} onCite={cite} />
        <Waterfall evidence={inv.evidence} onSelect={cite} />
        <h3>Timeline</h3>
        {inv.steps.length === 0 ? <p className="muted">No steps yet.</p> : (
          <ol className="timeline">{inv.steps.map((s) => (
            <li key={s.seq} className={`k-${s.kind}`}>
              <strong>{s.kind.replaceAll("_", " ")}</strong> {s.tool && <code>{s.tool}</code>} — {s.summary}
              {s.evidence_id && <> <button className="link" onClick={() => cite(s.evidence_id!)}>{s.evidence_id}</button></>}
              <div className="muted" style={{ fontSize: 12 }}><Time iso={s.created_at} /></div>
            </li>))}</ol>)}
      </section>}
      {view !== "analysis" && <EvidencePanel evidence={inv.evidence} focused={focused} />}
    </div>
  );
}

function Diagnosis({ inv, onCite }: { inv: InvestigationDetail; onCite: (id: string) => void }) {
  const d = inv.diagnosis;
  if (!d) return null;
  if (d.outcome === "insufficient_evidence") {
    return <div className="state denied"><strong>Insufficient evidence.</strong> The investigator would not guess.
      <ul>{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>{d.next_steps.length > 0 && <>Next: {d.next_steps.join("; ")}</>}</div>;
  }
  if (d.outcome === "no_incident") return <div className="state"><strong>No incident found</strong> in the current telemetry.</div>;
  return (
    <>
      <h3>Root-cause hypotheses</h3>
      {d.hypotheses.map((h) => (
        <article key={h.rank} className={`hyp ${h.rank === 1 ? "top" : ""}`} aria-label={`Hypothesis ${h.rank}`}>
          <div className="header-row"><strong>#{h.rank} {h.category.replaceAll("_", " ")} · {h.component}</strong>
            {h.faulty_setting && <code>{h.faulty_setting}</code>}<Badge value={h.confidence === "high" ? "passed" : h.confidence === "medium" ? "pending" : "expired"} label={`${h.confidence} confidence`} /></div>
          <p style={{ margin: "6px 0" }}>{h.summary}</p>
          <div>Supported by {h.evidence_ids.map((e) => <button key={e} className="link" onClick={() => onCite(e)}>{e}</button>)}
            {h.contradicting_evidence_ids.length > 0 && <> · contradicted by {h.contradicting_evidence_ids.map((e) => <button key={e} className="link" onClick={() => onCite(e)}>{e}</button>)}</>}</div>
        </article>))}
      {d.limitations.length > 0 && <p className="muted">Limitations: {d.limitations.join("; ")}</p>}
    </>
  );
}

export function EvidencePanel({ evidence, focused }: { evidence: Evidence[]; focused: string | null }) {
  const [tool, setTool] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const tools = Array.from(new Set(evidence.map((e) => e.tool))).sort();
  // A cited item stays visible even if a filter would hide it, so a citation never leads nowhere.
  const shown = evidence.filter((e) => e.id === focused
    || ((!tool || e.tool === tool) && (!failedOnly || !e.ok) && (!flaggedOnly || e.injection_flags.length > 0)));
  return (
    <section className="card" aria-labelledby="ev-h">
      <h2 id="ev-h">Evidence ({shown.length === evidence.length ? evidence.length : `${shown.length} of ${evidence.length}`})</h2>
      <p className="muted" style={{ fontSize: 13 }}>Raw results of the read-only tool calls. Content comes from the monitored system and is untrusted.</p>
      {evidence.length > 1 && (
        <div className="filters" role="group" aria-label="Filter evidence">
          <label>Tool <select value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">all</option>{tools.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
          <label><input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> failed calls only</label>
          <label><input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} /> flagged for injection only</label>
        </div>)}
      {shown.length === 0 && <p className="muted">No evidence matches the filters.</p>}
      {shown.map((e) => (
        <details key={e.id} id={`evidence-${e.id}`} className={`evidence-item ${focused === e.id ? "highlight" : ""}`} open={focused === e.id || undefined}>
          <summary><strong>{e.id}</strong> <code>{e.tool}</code> {e.ok ? <Badge value="passed" label="ok" /> : <Badge value="failed" label={e.error?.code ?? "error"} />}
            {" "}<span className="muted">{e.summary} · {Math.round(e.duration_ms)} ms{e.truncated && " · truncated"}</span>
            {e.injection_flags.length > 0 && <span className="flag"> · possible prompt injection: {e.injection_flags.join(", ")}</span>}</summary>
          <UntrustedBlock label="Arguments" value={e.arguments} />
          <UntrustedBlock label={e.ok ? "Result" : "Error"} value={e.ok ? e.data : e.error} />
        </details>))}
    </section>
  );
}
