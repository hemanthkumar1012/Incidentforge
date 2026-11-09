# Evaluation methodology

Runner: `lab/evaluate.py` (lab container: the only place ground truth exists). Scoring: `lab/scoring.py`.

```bash
make evaluate MODES=runbook TRIALS=3                    # credential-free
make evaluate MODES=runbook,llm_summary,llm TRIALS=5    # needs GEMINI_API_KEY in .env
```

## Compared modes

| Mode | What it is |
|---|---|
| `runbook` | Deterministic rules over a fixed signal set (no LLM). Baseline 1 |
| `llm_summary` | Same fixed signals, one Gemini call, no tools. Baseline 2 |
| `llm` | Tool-using Gemini investigator choosing its own queries within budgets |

All three use the same tool registry, bounds, evidence ledger and claim rules, and are driven through the public
API by ordinary operator and approver accounts.

## Trial procedure

reset → 5 healthy checkouts → inject scenario → 10 checkouts (failing) → wait one scrape → register an incident with
a neutral title → investigate → score → if diagnosed: validate → approve (second user) → execute → verify →
reset. Every trial starts from a full reset.

## Rubric

* **Correct hypothesis**: category in the accepted set for the ground-truth category
  (`dependency_errors` also accepts `dependency_unavailable`), component equals the root-cause component, and the
  faulty setting matches when the ground truth names one.
* **Top-1 / Top-3**: rank-1 / any rank ≤ 3 hypothesis is correct. Denominator: trials without runner errors.
* **Supported**: every hypothesis cites ≥ 1 successful evidence item and no unknown or failed IDs.
  *Unsupported rate* = diagnosed trials not supported / diagnosed trials.
* **Latency**: investigation `finished_at − started_at` (excludes queueing).
* **Tool calls, tokens**: from the investigation's recorded usage. **Estimated cost** = tokens × configured
  per-Mtok prices (`LLM_*_USD_PER_MTOK`); an estimate, not a bill.
* **Recovery**: recovery job `succeeded` and a checkout succeeds afterwards.
* **Policy violations**: production config versions created *during* the investigation (must be 0; investigators
  have no write path). Rejected tool calls (invalid arguments, permission denied) are reported separately.
* **Escalation**: whether a proposal was produced and whether its action matches the scenario's supported recovery.

## Scope and honesty

Only **S1** exists today, in the **development** split; there is no held-out set. Results describe behaviour on
one scenario and say nothing about generalisation; the report prints this limitation. **No benchmark numbers are
published in this repository** because no evaluation has been executed yet. Reports appear in `artifacts/eval/`
and in the UI's Evaluation page after a real run.
