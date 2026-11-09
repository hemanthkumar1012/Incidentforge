# Requirements → tests matrix

**PASS** = executed in the development environment (command in PROJECT_STATUS.md). **NOT RUN** = written; needs
PostgreSQL+psycopg, Docker, npm packages or a Gemini key, none of which were available. CI runs them all
(`.github/workflows/ci.yml`), but no CI run has been inspected yet.

| Requirement | Test | Status |
|---|---|---|
| Checkout flow, compensation, error mapping | tests/unit/test_orchestrator.py | PASS |
| Same idempotency key, simultaneous (logic) | test_orchestrator.py::test_concurrent_duplicate_requests_charge_once | PASS |
| Same key, simultaneous, separate DB connections | tests/db/test_checkout_db.py::test_simultaneous_same_key_one_order_one_charge | NOT RUN |
| Same key, different payload | test_orchestrator.py; test_checkout_db.py::test_same_key_different_payload_rejected | PASS / NOT RUN |
| Replay after completion | test_orchestrator.py; test_checkout_db.py::test_replay_after_completion_returns_same_order | PASS / NOT RUN |
| Uncertain payment outcome kept as `unknown`, retry settles | test_orchestrator.py; test_checkout_db.py::test_uncertain_payment_* | PASS / NOT RUN |
| Failure and restart during checkout (resume, single takeover) | test_orchestrator.py::test_stale_pending_*; test_checkout_db.py::test_crash_after_claim_* | PASS / NOT RUN |
| Reservation retries and concurrent duplicates | tests/db/test_reservations_db.py | NOT RUN |
| Admin hooks require token | test_reservations_db.py::test_admin_hooks_require_token | NOT RUN |
| Role boundaries (reader, remediator, sandbox) | psql probes; tests/db/test_roles_db.py | PASS / NOT RUN |
| Forge schema guarantees (one open approval, no self-approval, one job per proposal, append-only audit, catalogue-only actions, detector dedupe) | scripts/schema_probe.sh | PASS (PG16) |
| Migrations apply (shop 0001–0002, forge f0001–f0002) | f0001/f0002/shop-0002 SQL applied via psql (PASS); full Alembic run in tests/db/conftest.py | PASS (SQL) / NOT RUN (Alembic) |
| Requester self-approval refused (service + DB) | test_domain.py; test_forge_db.py::test_requester_cannot_self_approve_* | PASS / NOT RUN |
| Concurrent approval decisions | test_forge_db.py::test_two_approvers_race_exactly_one_decision | NOT RUN |
| Duplicate remediation execution | test_forge_db.py::test_duplicate_recovery_requests_create_one_job, ::test_duplicate_job_delivery_writes_production_once | NOT RUN |
| Stale config version (at request and at execution) | test_domain.py; test_forge_db.py::test_stale_config_*, ::test_config_moves_between_request_and_execution | PASS / NOT RUN |
| Validation for a different action does not authorize | test_domain.py (digest); test_forge_db.py::test_validation_for_a_different_action_does_not_authorize | PASS / NOT RUN |
| Failed validation cannot authorize | test_forge_db.py::test_failed_validation_cannot_authorize; UI: ActionPanel.test.tsx | NOT RUN |
| Non-reproduced failure not verified | test_remediation.py::test_not_reproducible_is_not_verified | PASS |
| Audit protections under the application role | schema_probe.sh (forge_app); test_forge_db.py::test_audit_events_append_only_* | PASS / NOT RUN |
| Sandbox mapping: explicit allowlist, unknown hosts unreachable, addresses rejected | test_remediation.py::test_sandbox_mapping_* | PASS |
| Sandbox reaches its dependencies, cannot reach production or the internet; sandbox creds refused by shop DB | scripts/sandbox_isolation_check.sh | NOT RUN |
| Validation runs start from reset state | test_remediation.py::test_each_validation_starts_from_reset_state | PASS |
| Tool schemas, bounds, permissions, timeouts, redaction | tests/unit/forge/test_tools.py | PASS |
| Malformed output, unsupported claims, insufficient evidence, tool failures, budget, provider errors, injection | tests/unit/forge/test_engine.py | PASS |
| Runbook diagnoses caller misconfiguration vs dependency down | tests/unit/forge/test_runbook.py | PASS |
| Fixed-summary baseline | test_engine.py::test_summary_baseline_one_call_over_fixed_signals | PASS |
| Planner: allowlisted action, exact params, side effects | tests/unit/forge/test_remediation.py | PASS |
| JWT/`alg=none`/scrypt; detector rule | tests/unit/forge/test_identity_detector.py | PASS |
| Ground-truth isolation, scripted provider unreachable | tests/unit/test_isolation.py | PASS |
| Evaluation rubric | tests/unit/test_lab.py::test_evaluation_rubric | PASS |
| Live Gemini integration | tests/live/test_gemini_smoke.py | NOT RUN |
| Frontend: API client errors/401/network | web/src/test/client.test.ts | NOT RUN |
| Frontend: exact-action approval, digest sent, self-approval hidden, failed/not-reproducible/stale states, refusal reasons, viewer has no actions | web/src/test/ActionPanel.test.tsx | NOT RUN |
| Frontend: untrusted logs as text, injection flag, empty/error/permission states, form validation | web/src/test/EvidenceAndStates.test.tsx | NOT RUN |
| Frontend syntax (all 21 TS/TSX files) | TypeScript transpile check | PASS |
| M1 healthy → fault → reset | scripts/m1_acceptance.py | NOT RUN |
| Full 13-step flow + rejection + self-approval + unauthorized + duplicate recovery | scripts/e2e_flow.py | NOT RUN |
| Evaluation execution | lab/evaluate.py (`make evaluate`) | NOT RUN |
| Bounded load | tools/loadgen.py (`make load`); no automated assertion yet | NOT RUN |
