# Known issues, audit findings and blockers

Each item has a status: **FIXED** (with the test that covers it), **OPEN**, or
**BLOCKED** (cannot be verified in the current environment).

## Session 2 audit of Milestone 1

| ID | Severity | Finding | Status |
|---|---|---|---|
| D1 | critical | Checkout idempotency was check-then-insert: two concurrent first requests with the same `Idempotency-Key` both passed the lookup, and the second hit the unique constraint, returning 500. | FIXED: atomic claim via `INSERT … ON CONFLICT (idempotency_key) DO NOTHING RETURNING`; concurrent duplicates get `409 request_in_progress` or a replay. Unit: `test_orchestrator.py::test_concurrent_duplicate_*`. DB: `tests/db/test_checkout_idempotency.py` (NOT RUN, needs psycopg). |
| D2 | critical | Checkout retries `reserve` after a timeout, but reservations were not idempotent, so a retry after a slow-but-successful first attempt decremented stock twice. | FIXED: one reservation per `order_ref` (unique index). A repeated reserve returns the existing hold; a concurrent duplicate loses the unique race and re-reads. DB test NOT RUN. |
| D3 | high | Reusing an idempotency key with a *different* body silently replayed the original order. | FIXED: request fingerprint stored with the order; a mismatch returns `422 idempotency_key_reused`. Unit-tested. |
| D4 | high | An inventory timeout could leave an orphaned stock hold (the server reserved after the client gave up). | FIXED: on inventory timeout/5xx, checkout releases any hold for the order ref (best effort, idempotent endpoint). Unit-tested. |
| D5 | medium | `lab_admin` had INSERT/UPDATE on *every* shop table via default privileges, including orders. | FIXED: default privileges removed; migration `0002` grants lab and forge roles access to `config_versions`/`change_events` only. |
| D6 | low | `ServiceRuntime.sessionmaker` was `Optional`, so every DB call site was type-unsafe. | FIXED: `ServiceRuntime.sessions` raises a clear error when the service was built without a DB. |

## Open

| ID | Finding | Notes |
|---|---|---|
| O1 | The payment simulator keeps idempotency results in memory; a restart forgets them. | Accepted for a simulator; documented. |
| O2 | The Jaeger v2 config keys and every image tag are unverified until the stack runs. | See docs/dependencies.md. |
| O3 | The repair catalogue has no feature-flag reset: the demo shop has no feature flags yet. | Planned with S3 in Milestone 4. |
| O4 | forge services, API, worker and HTTP adapters have never executed (no SQLAlchemy/FastAPI/httpx here). | First run will surface integration bugs; tests/db and tests/service are next. |
| O5 | Frontend written but never installed, type-checked, tested or built (npm blocked). | CI `web` job. |
| O6 | After a failed recovery verification there is no automatic rollback (by design: no unapproved writes). The rollback procedure must go through a new approval. | Documented trade-off. |
| O7 | Sandbox validation reproduces config state only; faults inside running services (latency, injected errors) are not copied, so such incidents validate as not_reproducible. | Documented in validation/runner.py. |

## Environment blockers (session 2)

| Blocker | Effect |
|---|---|
| No Docker daemon | Stack, service integration, E2E and Playwright tests: NOT RUN |
| No package-index access (pip/npm) | FastAPI, SQLAlchemy, Alembic, httpx, psycopg, prometheus-client, OTel SDK, google-genai, React, Vite, Vitest unavailable: API, DB and frontend tests NOT RUN; frontend build NOT RUN |
| No Gemini credentials or network in the sandbox | Live-provider smoke test: NOT RUN |

## Session 3 findings

| ID | Finding | Status |
|---|---|---|
| D7 | Payment timeout/5xx released stock and marked the order failed although the charge might have succeeded. | FIXED: order `unknown`, hold kept, `504 payment_outcome_unknown`; retry with same key resumes (docs/checkout-contract.md). |
| D8 | A crash after claiming left the order `pending` forever (every retry got 409). | FIXED: stale `pending` (> 30 s) is resumed by a retry; atomic takeover. |
| D9 | `recovery.request` set the approval to `invalidated` and then raised, so the rollback discarded the change, contradicting the documented behaviour. | FIXED: refuse without mutating; re-validation and expiry retire the approval. |
| D10 | Sandbox URL mapping passed unknown hosts and IP literals through unchanged, so isolation relied only on the network. | FIXED: allowlist; unknown → `unresolvable.invalid`; IP/localhost rejected. |
| D11 | docs/architecture.md still called the investigator "planned". | FIXED. |
| O8 | Session is per browser tab (in-memory token); approver and operator need separate tabs or profiles. | Documented trade-off (docs/security.md). |
| O9 | No automated bounded-load assertion (load generator only). | Open. |
