import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import { ErrorState, Loading, StaleNotice, Time } from "./ui";

// Recent entries from the append-only audit log, newest first. Everything shown is a recorded event;
// actor and action names are server-generated identifiers and are rendered as text.
export function ActivityFeed({ limit = 12 }: { limit?: number }) {
  const q = usePolling((s) => api.audit(limit, s), 8_000);
  if (q.loading) return <Loading what="recent activity" />;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refresh} />;
  const items = q.data?.items ?? [];
  return (
    <>
      <StaleNotice stale={q.stale} lastUpdated={q.lastUpdated} />
      {items.length === 0 ? <p className="muted">No activity recorded yet.</p> : (
        <ol className="timeline" aria-label="Recent audit events">
          {items.map((e) => (
            <li key={e.id}>
              <strong>{e.action.replaceAll("_", " ").replaceAll(".", " · ")}</strong>
              <span className="muted"> by {e.actor} on {e.subject_type}</span>
              <div className="muted" style={{ fontSize: 12 }}><Time iso={e.occurred_at} /></div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
