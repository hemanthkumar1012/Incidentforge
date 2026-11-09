import { useEffect, useRef, type ReactNode } from "react";
import { ApiError } from "../api/client";

const TONE: Record<string, string> = {
  open: "warn", investigating: "info", diagnosed: "info", remediating: "info", resolved: "ok", closed: "muted",
  queued: "muted", running: "info", completed: "ok", insufficient_evidence: "warn", budget_exhausted: "warn",
  failed: "bad", cancelled: "muted", proposed: "muted", validating: "info", validated: "ok",
  validation_failed: "bad", not_reproducible: "warn", superseded: "muted", executed: "ok", passed: "ok",
  error: "bad", pending: "warn", approved: "ok", rejected: "bad", expired: "muted", invalidated: "warn",
  consumed: "ok", requested: "info", executing: "info", verifying: "info", succeeded: "ok",
  verification_failed: "bad", refused: "bad", rolled_back: "warn", sev1: "bad", sev2: "warn", sev3: "muted",
};

export function Badge({ value, label }: { value: string; label?: string }) {
  return <span className={`badge tone-${TONE[value] ?? "muted"}`}>{label ?? value.replaceAll("_", " ")}</span>;
}

// Absolute local time with the UTC offset; full ISO value on hover. No relative-only times.
export function Time({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="muted">—</span>;
  const d = new Date(iso);
  const text = d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium", timeZoneName: "short" });
  return <time dateTime={iso} title={iso}>{text}</time>;
}

export function Loading({ what }: { what: string }) {
  return <p className="state" role="status" aria-live="polite">Loading {what}…</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state empty">{children}</div>;
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  if (error.isForbidden) {
    return <div className="state denied" role="alert"><strong>Permission denied.</strong> {error.message}</div>;
  }
  return (
    <div className="state failed" role="alert">
      <strong>Request failed.</strong> {error.message} <code>{error.code}</code>
      {onRetry && <button className="link" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function StaleNotice({ stale, lastUpdated }: { stale: boolean; lastUpdated: Date | null }) {
  if (!stale) return null;
  return (
    <p className="stale" role="status">
      Live updates failing; showing data from {lastUpdated?.toLocaleTimeString() ?? "earlier"}. Retrying with backoff.
    </p>
  );
}

// Untrusted content (logs, trace attributes, change descriptions) is only ever
// rendered as text inside <pre>. React escapes it; nothing is parsed as HTML or links.
export function UntrustedBlock({ value, label }: { value: unknown; label: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <figure className="untrusted">
      <figcaption>{label} <span className="muted">· untrusted system data, shown as text</span></figcaption>
      <pre tabIndex={0}>{text}</pre>
    </figure>
  );
}

export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, onConfirm, onCancel }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close?.();
  }, [open]);
  if (!open) return null;
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="dialog-title" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2 id="dialog-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button onClick={onCancel} disabled={busy}>Cancel</button>
        <button className={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy} autoFocus>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}

export function ChangeTable({ changes }: { changes: { key: string; op: string; old?: unknown; new?: unknown }[] }) {
  if (!changes.length) return <p className="muted">No changes.</p>;
  return (
    <table className="table compact">
      <thead><tr><th scope="col">Setting</th><th scope="col">Current</th><th scope="col">After</th></tr></thead>
      <tbody>{changes.map((c) => (
        <tr key={c.key}><td><code>{c.key}</code></td><td><code>{String(c.old ?? "—")}</code></td><td><code>{String(c.new ?? "—")}</code></td></tr>
      ))}</tbody>
    </table>
  );
}
