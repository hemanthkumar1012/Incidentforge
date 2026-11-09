import { api } from "../api/client";
import { Badge, ErrorState, Loading, StaleNotice, Time } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

export function Overview() {
  const { data, error, loading, stale, lastUpdated, refresh } = usePolling((s) => api.overview(s), 10_000);
  if (loading) return <Loading what="system overview" />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;
  const config = data.checkout_config && "version" in data.checkout_config ? data.checkout_config : null;

  return (
    <>
      <h1>System overview</h1>
      <p className="muted">Queried live from the services every 10 s{lastUpdated && <> · last update {lastUpdated.toLocaleTimeString()}</>}.</p>
      <StaleNotice stale={stale} lastUpdated={lastUpdated} />
      <div className="grid two">
        <section className="card" aria-labelledby="svc-h">
          <h2 id="svc-h">Service readiness</h2>
          <table className="table">
            <thead><tr><th scope="col">Service</th><th scope="col">Ready</th><th scope="col">Detail</th></tr></thead>
            <tbody>{Object.entries(data.services).map(([name, s]) => (
              <tr key={name}><td>{name}</td><td><Badge value={s.ready ? "passed" : "failed"} label={s.ready ? "ready" : "not ready"} /></td>
                <td className="muted">{s.error ?? (s.status_code ? `HTTP ${s.status_code}` : "")}</td></tr>
            ))}</tbody>
          </table>
        </section>
        <section className="card" aria-labelledby="dep-h">
          <h2 id="dep-h">Service relationships</h2>
          <ul>{Object.entries(data.topology).map(([svc, deps]) => (
            <li key={svc}><strong>{svc}</strong> → {deps.length ? deps.join(", ") : <span className="muted">no dependencies</span>}</li>
          ))}</ul>
          {config && <>
            <h3>Checkout endpoints (config v{config.version})</h3>
            <ul>{Object.entries(config.payload).filter(([k]) => k.endsWith("_url")).map(([k, v]) => <li key={k}><code>{k}</code>: <code>{String(v)}</code></li>)}</ul>
          </>}
          {data.checkout_config && "error" in data.checkout_config && <p className="field-error">Config unavailable: {data.checkout_config.error}</p>}
        </section>
        <section className="card" aria-labelledby="cfg-h">
          <h2 id="cfg-h">Checkout config history</h2>
          <table className="table compact">
            <thead><tr><th scope="col">Version</th><th scope="col">Author</th><th scope="col">Created</th></tr></thead>
            <tbody>{data.config_versions.map((v) => (
              <tr key={v.version}><td>v{v.version} {v.active && <Badge value="passed" label="active" />}</td><td>{v.author}</td><td><Time iso={v.created_at} /></td></tr>
            ))}</tbody>
          </table>
        </section>
        <section className="card" aria-labelledby="inv-h">
          <h2 id="inv-h">Investigator settings</h2>
          <dl>
            <dt>Default mode</dt><dd>{data.investigation_default_mode}</dd>
            <dt>LLM</dt><dd>{data.llm_configured ? `Gemini (${data.llm_model})` : "not configured (runbook mode only)"}</dd>
            <dt>Investigator scopes (read-only)</dt><dd>{data.investigator_scopes.join(", ")}</dd>
          </dl>
        </section>
      </div>
    </>
  );
}
