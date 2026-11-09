import { api } from "../api/client";
import { DependencyMap } from "../components/DependencyMap";
import { Badge, ErrorState, Kpi, Loading, StaleNotice, Time } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

export function Overview() {
  const { data, error, loading, stale, lastUpdated, refresh } = usePolling((s) => api.overview(s), 10_000);
  if (loading) return <Loading what="system overview" />;
  if (error && !data) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;

  const config = data.checkout_config && "version" in data.checkout_config ? data.checkout_config : null;
  const services = Object.entries(data.services);
  const ready = services.filter(([, s]) => s.ready).length;
  const allReady = services.length > 0 && ready === services.length;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>System overview</h1>
          <p className="muted">Queried live from the services every 10 s{lastUpdated && <> · last update {lastUpdated.toLocaleTimeString()}</>}.</p>
        </div>
        <button onClick={refresh}>Refresh now</button>
      </div>
      <StaleNotice stale={stale} lastUpdated={lastUpdated} />

      <div className="kpis">
        <Kpi label="Services ready" value={services.length ? `${ready} / ${services.length}` : "—"}
          edge={!services.length ? undefined : allReady ? "ok" : "bad"}
          hint={allReady ? "all readiness probes passing" : services.length ? "see the map below" : "no services reported"} />
        <Kpi label="Active checkout config" value={config ? `v${config.version}` : "—"} edge={config ? "info" : "warn"}
          hint={config ? `${data.config_versions.length} versions recorded` : "configuration unavailable"} />
        <Kpi label="Investigator" value={data.investigation_default_mode}
          hint={data.llm_configured ? `Gemini · ${data.llm_model}` : "no LLM key: runbook mode only"} edge="info" />
        <Kpi label="Investigator access" value="read-only" hint={`${data.investigator_scopes.length} scopes`} edge="ok" />
      </div>

      <div className="grid two">
        <section className="card" aria-labelledby="map-h">
          <h2 id="map-h">Service dependency map</h2>
          <DependencyMap topology={data.topology} services={data.services} />
          {data.checkout_config && "error" in data.checkout_config && <p className="field-error">Config unavailable: {data.checkout_config.error}</p>}
        </section>

        <section className="card" aria-labelledby="svc-h">
          <h2 id="svc-h">Service readiness</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th scope="col">Service</th><th scope="col">Ready</th><th scope="col">Detail</th></tr></thead>
              <tbody>{services.map(([name, s]) => (
                <tr key={name}><td>{name}</td>
                  <td><Badge value={s.ready ? "passed" : "failed"} label={s.ready ? "ready" : "not ready"} /></td>
                  <td className="muted">{s.error ?? (s.status_code ? `HTTP ${s.status_code}` : "")}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </section>

        <section className="card" aria-labelledby="cfg-h">
          <h2 id="cfg-h">Checkout configuration</h2>
          {config && (
            <>
              <h3>Endpoints in v{config.version}</h3>
              <ul>{Object.entries(config.payload).filter(([k]) => k.endsWith("_url")).map(([k, v]) => (
                <li key={k}><code>{k}</code>: <code>{String(v)}</code></li>
              ))}</ul>
            </>
          )}
          <h3>History</h3>
          <div className="table-wrap">
            <table className="table compact">
              <thead><tr><th scope="col">Version</th><th scope="col">Author</th><th scope="col">Created</th></tr></thead>
              <tbody>{data.config_versions.map((v) => (
                <tr key={v.version}><td>v{v.version} {v.active && <Badge value="passed" label="active" />}</td><td>{v.author}</td><td><Time iso={v.created_at} /></td></tr>
              ))}</tbody>
            </table>
          </div>
        </section>

        <section className="card" aria-labelledby="inv-h">
          <h2 id="inv-h">Investigator settings</h2>
          <dl>
            <dt className="muted">Default mode</dt><dd>{data.investigation_default_mode}</dd>
            <dt className="muted">LLM</dt><dd>{data.llm_configured ? `Gemini (${data.llm_model})` : "not configured (runbook mode only)"}</dd>
            <dt className="muted">Investigator scopes (read-only)</dt>
            <dd className="chips">{data.investigator_scopes.map((s) => <Badge key={s} value="muted" label={s} />)}</dd>
          </dl>
        </section>
      </div>
    </>
  );
}
