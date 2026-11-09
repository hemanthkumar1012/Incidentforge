import { api } from "../api/client";
import { EvalCharts } from "../components/EvalCharts";
import { Empty, ErrorState, Loading } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

export function Evaluation() {
  const q = usePolling((s) => api.evaluations(s), 60_000);
  if (q.loading) return <Loading what="evaluation results" />;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refresh} />;
  const runs = q.data?.runs ?? [];
  return (
    <>
      <h1>Evaluation results</h1>
      <p className="muted">Results files written by <code>lab evaluate</code> from actual trials. Nothing on this page is computed or estimated by the UI.</p>
      {runs.length === 0 ? <Empty>No evaluation has been run yet. Run <code>make evaluate</code> (see docs/evaluation.md); results appear here.</Empty> :
        runs.map((run, idx) => run.error ? <ErrorStateLine key={idx} text={`${run.file}: ${run.error}`} /> : (
          <section key={run.generated_at} className="card" aria-label={`Evaluation ${run.generated_at}`}>
            <h2>Run {run.generated_at}</h2>
            <p>Scenarios: {run.scenarios?.join(", ")} · trials: {run.trials?.length ?? 0}</p>
            {(run.scenarios?.length ?? 0) < 3 && <p className="state denied"><strong>Limited scope:</strong> only {run.scenarios?.length} scenario(s). These results do not show generalisation.</p>}
            <EvalCharts rows={run.summary ?? []} />
            <div style={{ overflowX: "auto" }}><table className="table compact">
              <thead><tr>{Object.keys(run.summary?.[0] ?? {}).map((k) => <th key={k} scope="col">{k.replaceAll("_", " ")}</th>)}</tr></thead>
              <tbody>{run.summary?.map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{v === null ? "—" : String(v)}</td>)}</tr>)}</tbody>
            </table></div>
          </section>))}
    </>
  );
}

function ErrorStateLine({ text }: { text: string }) {
  return <p className="field-error">{text}</p>;
}
