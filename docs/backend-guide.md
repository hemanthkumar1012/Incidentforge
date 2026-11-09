# Control-plane backend guide (`forge/`)

## Module map and dependency direction

```
api/  ──► services/ ──► domain/            (pure rules: states, binding, policy, detection)
  │          │    └───► investigation/     (engine, runbook, tools, evidence, providers)
  │          │    └───► remediation/, validation/runner.py   (pure planning / orchestration)
  │          └──► db/models.py, jobs/queue.py
  └──► wiring.py (composition root) ──► telemetry/*, validation/sandbox_adapter.py (I/O adapters)
jobs/worker.py ──► services/ + wiring.py
```

Arrows point at what a module may import. `domain/`, `investigation/` (except
`providers/gemini.py`), `remediation/` and `validation/runner.py` do no I/O and
are unit-tested in isolation. Only `wiring.py` knows which adapter backs which port.

| Module | Responsibility |
|---|---|
| `domain/states.py` | Transition tables for incident, investigation, proposal, approval and recovery. |
| `domain/binding.py` | SHA-256 digest binding an approval to action, target, params, expected config version and validation run. |
| `domain/policy.py` | Roles → permissions; approval and execution refusals (separation of duties, expiry, digest, config version). |
| `investigation/toolkit.py` | Bounded tool execution: exists → scope → schema → timeout → redact and cap. |
| `investigation/tool_catalog.py` | The 8 read-only tools and their input bounds. |
| `investigation/engine.py` | LLM loop with budgets, provider retries, correction of malformed or unsupported output. |
| `investigation/runbook.py` | Deterministic investigator (baseline and credential-free mode). |
| `investigation/evidence.py` | Evidence ledger (E1…), injection flags, claim checking. |
| `remediation/planner.py` | Diagnosis plus real config history → one allowlisted action with exact parameters. |
| `validation/runner.py` | Reproduce → repair → regression in the sandbox; verdicts. |
| `services/*` | Transactions, persistence, audit; one public function per use case. |
| `jobs/queue.py`, `jobs/worker.py`, `jobs/detector.py` | Postgres job queue, worker loop, threshold detector. |
| `api/*` | FastAPI routers: parse, authorize, call one service, serialize. |

## Transaction boundaries

* **API request = one transaction** (`api/deps.py::db`): committed if the handler returns, rolled back if it raises.
  Services flush but never commit, so a state change, its audit event and any enqueued job commit atomically.
* **Worker jobs** use short transactions around each phase (claim, start, record progress, finish). Long calls
  (LLM, telemetry, sandbox checks, production verification) happen *outside* any transaction, so no locks are
  held while waiting on the network.
* Investigation steps and evidence are committed one by one, so the UI sees progress while a run is in flight.

## State transitions

See `domain/states.py` (the tables are the documentation). Notable rules:

* A proposal can reach `executed` only from `validated`.
* An approval moves `pending → approved → consumed`; it becomes `invalidated` if the proposal is re-validated
  or production config moves, and `expired` 15 minutes after the request.
* Recovery: `requested → executing → verifying → succeeded | verification_failed`, or `refused` when preconditions
  fail at execution time.

## Background jobs

`jobs` table, claimed with `FOR UPDATE SKIP LOCKED`; 10-minute lease; stale leases are requeued. Investigation and
validation jobs retry once (`max_attempts=2`). Recovery jobs never retry automatically (`max_attempts=1`), because
a retried production write must be a human decision. Each handler checks the subject's current status first,
so a duplicate delivery is a no-op.

## Error handling

`services/common.py` defines `NotFound` (404), `Forbidden` (403), `Conflict` (409, includes illegal transitions)
and `PreconditionFailed` (412). The API maps them to `{"error": {"code", "message", "details"}}`. Tool and
telemetry failures are data (structured tool errors stored as evidence), not exceptions. Unexpected exceptions
in a job are logged with a traceback and recorded on the job row.

## Retry and timeout policy

| Call | Timeout | Retries |
|---|---|---|
| Tool handler (backstop) | 8 s (12 s diagnostics) | none (model or runbook decides) |
| Prometheus / Loki / Jaeger HTTP | 5 s | none |
| Gemini `generateContent` | 60 s | 3 attempts, exponential backoff (1 s, 2 s) on timeout, 429, 5xx |
| Malformed model output | n/a | up to 3 corrections, then the run fails |
| Investigation budget | 240 s, 16 turns, 12 tool calls, 200k tokens | ends as `budget_exhausted` |
| Checkout → inventory/payment | per-config (2 s) | 1 retry on connect error, timeout, 5xx (payment uses an idempotency key) |

## Concurrency

| Race | Protection |
|---|---|
| Two checkouts, same idempotency key | `INSERT … ON CONFLICT DO NOTHING RETURNING` claim |
| Retried inventory reserve | unique `reservations.order_ref`; loser re-reads |
| Two approvers decide at once | `SELECT … FOR UPDATE` on the approval |
| Two execute requests | existing-job check, conditional `UPDATE approvals … WHERE status='approved'`, unique `recovery_jobs.proposal_id` |
| Config changed after approval | digest + `expected_active_version` re-checked at request **and** inside `apply_config` under an advisory lock |
| Two open approvals for one proposal | partial unique index `uq_approvals_one_open` |
| Duplicate detector incidents | partial unique index `uq_incidents_one_open_detector` |

## Investigator access boundary

The investigator process holds: Prometheus/Loki/Jaeger read URLs, the `forge_reader` DB role (SELECT on
`config_versions` and `change_events` only), and readiness/TCP probes restricted to known services and the
endpoints in checkout's own config. It holds no lab credentials, no lab code (the image excludes `lab/`), no
shop write role, and no Docker socket. The remediation write path (`forge_remediator`) is used only by the
recovery executor after approval, never by a tool.
