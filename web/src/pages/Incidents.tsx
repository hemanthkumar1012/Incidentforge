import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorState, Loading, StaleNotice, Time } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

const STATUSES = ["", "open", "investigating", "diagnosed", "remediating", "resolved", "closed"];

export function Incidents() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const sort = params.get("sort") ?? "created_at";
  const order = params.get("order") ?? "desc";
  const page = Number(params.get("page") ?? "1");
  const { can } = useAuth();
  const list = usePolling((s) => api.incidents({ status, q, sort, order, page }, s), 15_000, () => true,
                          [status, q, sort, order, page]);
  const set = (k: string, v: string) => { const next = new URLSearchParams(params); if (v) next.set(k, v); else next.delete(k); if (k !== "page") next.delete("page"); setParams(next); };
  const sortBy = (col: string) => {
    const next = new URLSearchParams(params);
    next.set("order", sort === col && order === "desc" ? "asc" : "desc");
    next.set("sort", col);
    next.delete("page");
    setParams(next);
  };
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;

  return (
    <>
      <div className="page-head"><div className="grow"><h1>Incidents</h1>
        <p className="muted">Opened by the detector or registered by a responder. Select one to investigate and repair.</p></div></div>
      <div className="toolbar" role="search">
        <div className="field"><label htmlFor="q">Search titles</label>
          <input id="q" defaultValue={q} onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value); }} /></div>
        <div className="field"><span id="status-l" style={{ display: "block", fontWeight: 600, fontSize: 13, marginBottom: 4 }}>Status</span>
          <div className="chips" role="group" aria-labelledby="status-l">
            {STATUSES.map((s) => (
              <button key={s} className="chip" aria-pressed={status === s} onClick={() => set("status", s)}>{s || "all"}</button>))}
          </div></div>
      </div>
      {can("incident:register") && <RegisterIncident />}
      <StaleNotice stale={list.stale} lastUpdated={list.lastUpdated} />
      {list.loading ? <Loading what="incidents" /> : list.error && !list.data ? <ErrorState error={list.error} onRetry={list.refresh} /> :
        !list.data?.items.length ? <Empty>No incidents match. The detector opens one automatically when checkout failures cross the threshold, or register one manually.</Empty> : (
        <div className="card">
          <div className="table-wrap"><table className="table">
            <thead><tr>
              <th scope="col">Title</th>
              <th scope="col" aria-sort={sort === "severity" ? (order === "asc" ? "ascending" : "descending") : "none"}><button onClick={() => sortBy("severity")}>Severity</button></th>
              <th scope="col" aria-sort={sort === "status" ? (order === "asc" ? "ascending" : "descending") : "none"}><button onClick={() => sortBy("status")}>Status</button></th>
              <th scope="col">Source</th>
              <th scope="col" aria-sort={sort === "created_at" ? (order === "asc" ? "ascending" : "descending") : "none"}><button onClick={() => sortBy("created_at")}>Opened</button></th>
            </tr></thead>
            <tbody>{list.data.items.map((i) => (
              <tr key={i.id}>
                <td><Link to={`/incidents/${i.id}`}>{i.title}</Link>{i.synthetic_traffic && <span className="muted"> · synthetic traffic</span>}</td>
                <td><Badge value={i.severity} /></td><td><Badge value={i.status} /></td><td>{i.source}</td><td><Time iso={i.created_at} /></td>
              </tr>))}</tbody>
          </table></div>
          <nav className="pager" aria-label="Pagination">
            <button disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Previous</button>
            <span>Page {page} of {pages} · {list.data.total} incidents</span>
            <button disabled={page >= pages} onClick={() => set("page", String(page + 1))}>Next</button>
          </nav>
        </div>)}
    </>
  );
}

function RegisterIncident() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("sev2");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 5) { setError("Title must be at least 5 characters."); return; }
    setBusy(true); setError(null);
    try { const created = await api.registerIncident(title.trim(), severity, description); navigate(`/incidents/${created.id}`); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  return (
    <details className="card"><summary><strong>Register an incident</strong></summary>
      <form onSubmit={submit} noValidate style={{ marginTop: 12 }}>
        <div className="field"><label htmlFor="title">Title</label>
          <input id="title" value={title} maxLength={200} aria-invalid={!!error} aria-describedby="title-err" onChange={(e) => setTitle(e.target.value)} /></div>
        <div className="field"><label htmlFor="sev">Severity</label>
          <select id="sev" value={severity} onChange={(e) => setSeverity(e.target.value)}><option>sev1</option><option>sev2</option><option>sev3</option></select></div>
        <div className="field"><label htmlFor="desc">What are you seeing? (optional)</label>
          <textarea id="desc" rows={3} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
        {error && <p id="title-err" className="field-error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>{busy ? "Registering…" : "Register incident"}</button>
      </form>
    </details>
  );
}
