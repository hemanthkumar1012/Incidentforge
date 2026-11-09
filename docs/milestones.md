# Milestone checklist and acceptance tests

A box is ticked only when its acceptance test has actually been run and passed.
"Implemented" means the code exists but has not yet passed its acceptance test
end to end.

## Milestone 1 — demo app, telemetry, one fault, reliable reset

Status: **implemented, unit-tested; end-to-end acceptance not yet run** (see PROJECT_STATUS.md)

- [ ] Stack starts: `make up` → `tools/wait_ready.py` reports checkout, prometheus, loki, jaeger ready
- [ ] Successful checkout: `make journey` exits 0 (`outcome: success`)
- [ ] Declined card is a clean 402: `python3 tools/journey.py --card tok_test_decline --expect declined`
- [ ] S1 injection: `make inject-S1` prints `SYNTHETIC INJECTED INCIDENT`
- [ ] Failure observed: `make journey-fail` exits 0, error code `dependency_unavailable`
- [ ] Metrics: `shop_dependency_requests_total{dependency="payment",outcome="connect_error"}` > 0
- [ ] Logs: Loki returns checkout `dependency call failed` lines with `fields.target="payment:8020"`
- [ ] Traces: Jaeger returns checkout traces tagged `error=true`
- [ ] Reset: `make reset` exits 0 with every service ready; `make journey` succeeds again
- [x] Unit tests: `make test` (55 tests: orchestrator, lab controller, config schema, redaction, Loki handler, faults, journey tool, isolation)
- [x] Lint: `ruff check .`
- [x] Compose file validates and refuses to start without secrets
- [x] Postgres init script and role permissions verified on Postgres 16

All of the unticked items are automated in `make acceptance` (`scripts/m1_acceptance.py`) and in the CI `acceptance` job.

## Milestone 2 — read-only investigator diagnoses S1 from real telemetry

- Gemini provider adapter behind a provider-neutral interface; structured, schema-validated outputs
- Typed read-only tools: `query_metrics`, `search_logs`, `find_traces`, `get_trace`,
  `get_service_dependencies`, `get_recent_changes`, `get_configuration_diff`, `run_allowlisted_diagnostic`
- Each tool: input validation, bounded windows and sizes, timeouts, permission checks, redaction, structured errors
- Tool results wrapped as untrusted data (protection against instructions embedded in logs)
- Investigation budget (tool calls, tokens, wall time); evidence store with IDs; diagnosis schema
  with ranked hypotheses, evidence references, limitations, "insufficient evidence"
- Forge DB (incidents, investigations, tool calls, evidence, audit events) via Alembic

Acceptance: with S1 injected, `POST /investigations` produces a top-ranked
`configuration_error` hypothesis on checkout `payment_url` whose cited evidence
IDs resolve to real stored tool results; with no fault injected, the result is
"no incident"/insufficient evidence. Tests assert that the investigator image
and its prompts contain no scenario IDs or ground truth.

## Milestone 3 — isolated validation, exact-action approval, verified recovery

- Repair catalogue: restore previous config, reset demo feature flag, roll back config version
- Proposal schema: action type, exact target, expected effect, evidence, preconditions,
  validation procedure, rollback procedure, approval requirement
- Disposable validation environment (separate compose project, own DB); reproduce → confirm
  failure → apply repair → recovery tests → regression checks; "not verified" if reproduction fails
- Approval state machine bound to a hash of (action, target, params, expected config version);
  stale-approval and duplicate-execution protection; operator/approver roles
- Execution through the config write path with `expected_active_version`; post-execution recovery verification

Acceptance: the 10-step vertical slice in the project brief, end to end, with an audit trail.

## Milestone 4 — more faults, dashboard, evaluation, security tests, docs

- Scenarios S2 (slow inventory), S3 (payment errors), S4 (invalid config), S5 (DB pool, only if reliably reproducible)
- React/TS/Vite dashboard pages listed in the brief, all backed by API state
- Evaluation runner: runbook baseline vs. fixed-summary LLM vs. tool-using investigator;
  dev/held-out split; repeated trials; report with denominators
- Security tests (authz on every state-changing endpoint, prompt-injection fixtures), threat model, API docs
