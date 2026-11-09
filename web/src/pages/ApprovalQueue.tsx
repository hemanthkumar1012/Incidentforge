import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ExpiryMeter } from "../components/ExpiryMeter";
import { Badge, ChangeTable, Empty, ErrorState, Loading, StaleNotice, Time } from "../components/ui";
import { usePolling } from "../hooks/usePolling";
import { DecisionButtons } from "./workspace/ActionPanel";

export function ApprovalQueue() {
  const [status, setStatus] = useState("pending");
  const q = usePolling((s) => api.approvals(status, s), 10_000, () => true, [status]);
  return (
    <>
      <h1>Approval queue</h1>
      <p className="muted">Each approval covers exactly one action, bound by the digest shown. Requesters cannot approve their own actions.</p>
      <div className="toolbar"><div className="field"><label htmlFor="ast">Status</label>
        <select id="ast" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["pending", "approved", "rejected", "expired", "invalidated", "consumed"].map((s) => <option key={s}>{s}</option>)}
        </select></div></div>
      <StaleNotice stale={q.stale} lastUpdated={q.lastUpdated} />
      {q.loading ? <Loading what="approvals" /> : q.error && !q.data ? <ErrorState error={q.error} onRetry={q.refresh} /> :
        !q.data?.items.length ? <Empty>No {status} approvals.</Empty> : q.data.items.map((a) => (
          <section key={a.id} className="card" aria-label={`Approval ${a.id}`}>
            <div className="header-row"><h2 style={{ margin: 0 }}>{String(a.binding.action_type)} on {String(a.binding.target)}</h2><Badge value={a.status} /></div>
            <p className="muted">Requested by {a.requested_by} · <Time iso={a.requested_at} /> · expires <Time iso={a.expires_at} /> {a.status === "pending" && <ExpiryMeter requestedAt={a.requested_at} expiresAt={a.expires_at} />}
              {a.incident_id && <> · <Link to={`/incidents/${a.incident_id}`}>open incident</Link></>}</p>
            <ChangeTable changes={a.expected_effect ?? []} />
            <p className="muted" style={{ fontSize: 13 }}>Binding digest <code>{a.binding_digest}</code></p>
            {a.status === "pending" && <DecisionButtons approval={a} onDone={q.refresh} />}
            {a.decided_by && <p>Decided by {a.decided_by} · <Time iso={a.decided_at} />{a.note && <> · “{a.note}”</>}</p>}
          </section>))}
    </>
  );
}
