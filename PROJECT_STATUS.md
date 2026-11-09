# PROJECT_STATUS

Last updated: 2026-11-08, end of session 3.

**Overall: implementation-complete for the core product flow, runtime-unverified.** Frontend, PostgreSQL
integration tests, the E2E harness, the evaluation runner, CI and the documentation now exist. None of the
stack-, database-driver-, frontend- or Gemini-dependent tests have executed. The project is **not** complete
until they run green (Definition of Done).

## Environment blockers (unchanged)

No Docker daemon; pip/npm cannot reach package indexes (FastAPI, SQLAlchemy, httpx, psycopg, React, Vite, Vitest
unavailable); no Gemini key or network. Available: Python 3.13, pydantic, pytest, mypy, ruff, Postgres 16 server +
psql, Node 22 + TypeScript (no React types).

## Results: commands actually executed in session 3

| Command | Result |
|---|---|
| `python3 -m pytest tests -q` | **154 passed, 2 skipped** (tests/db and tests/live skip: no psycopg / no key) |
| `ruff check .` · `ruff format --check .` | PASS · PASS |
| `python3 -m mypy <31 pure modules>` (strict) | PASS |
| `python3 -m compileall -q shop lab forge tools scripts tests` | PASS |
| `docker compose config --quiet` (example .env) | PASS (16 services) |
| `bash -n` on shell scripts | PASS |
| `scripts/schema_probe.sh` on PG16 | PASS 10/10 |
| forge `f0002` and shop `0002` SQL applied on PG16 (stubbed `alembic.op`) | PASS |
| TypeScript transpile of all 52 web files (after the layout redesign, palette, waterfall, countdown, report, graph and chart work) | PASS (syntax only; no type check, no build, vitest not run) |
| Pure logic added with the redesign (`lib/workflow.ts`, `graph.ts`, `palette.ts`, `timing.ts`, `countdown.ts`, `report.ts`, `evidenceGraph.ts`, `evalCharts.ts`) | PASS when compiled with tsc and run in node on the cases in the new tests; the vitest files themselves NOT RUN |

## NOT RUN (written, blocked)

`tests/db/*` (PostgreSQL races, crash/restart, roles, approvals, duplicate execution, audit) · `web` lint/typecheck/
Vitest/build · `scripts/m1_acceptance.py` · `scripts/e2e_flow.py` · `scripts/sandbox_isolation_check.sh` ·
`lab evaluate` · `tests/live` (Gemini) · CI (no run inspected). **No benchmark results exist.**

## Files changed in session 3

- Contract fixes: shop/checkout/{orchestrator,repository,app}.py (D7 uncertain payment, D8 crash resume, Retry-After);
  forge/services/recovery.py (D9); forge/validation/runner.py (D10 allowlist mapping).
- New mode: forge/investigation/summary_baseline.py, forge/migrations/versions/0002_summary_mode.py, wiring/API.
- Tests: tests/unit (orchestrator, remediation, engine, lab additions), tests/db/{conftest,test_checkout_db,
  test_reservations_db,test_forge_db,test_roles_db}.py, tests/live/test_gemini_smoke.py.
- Harness: scripts/e2e_flow.py, scripts/sandbox_isolation_check.sh; Makefile targets.
- Evaluation: lab/evaluate.py, lab/scoring.py, `lab evaluate`, GET /api/evaluations.
- Frontend: web/ (Vite+React+TS, typed client, polling hook, 6 pages incl. incident workspace, 3 test files,
  Dockerfile+nginx), compose `web` on :3000.
- Frontend layout (session 4): sidebar shell with breadcrumbs, dark/light theme, live pending-approvals count, KPI tiles,
  service dependency map drawn from the live topology, response-progress stepper derived from workflow records, URL-addressable
  tabs in the incident workspace, toasts, status filter chips, Ctrl/Cmd+K command palette with live incident search,
  g-prefixed keyboard shortcuts, audit-log activity feed, server-counted active-incident tile, tool-call waterfall, evidence filters, live approval expiry meter (display-only), Markdown/JSON incident export,
  hypothesis-to-evidence graph, evaluation bar charts that print raw counts.
  Robustness: per-route error boundary, lazy-loaded pages, focus/title/live-region announcement on navigation (not yet exercised in a browser). Not rendered in a browser; visual quality and contrast are unchecked.
- CI: .github/workflows/ci.yml (backend+db+schema+audit, gitleaks, web, acceptance with sanitized artifacts).
- Docs: README, operations, security, states, checkout-contract, evaluation, requirements-tests, known-issues,
  architecture.

## Remaining issues

O1 payment simulator idempotency in memory · O2 image tags and Jaeger config unverified · O3 no feature-flag
action · O4 forge services/API/worker never executed · O5 frontend never built · O7 sandbox reproduces config
state only · O8 per-tab session · O9 no automated load assertion. Expect first-run integration bugs.

## Exact next task

On a machine with Docker, Node and network: `cp .env.example .env` (edit) → `pip install -r requirements/dev.txt`
→ `TEST_ADMIN_DSN=... make test-db` → `cd web && npm install && npm run typecheck && npm test && npm run build`
→ `make up && make acceptance && make sandbox-check && make e2e` → fix failures, recording each as PASS/FAIL here →
`make evaluate MODES=runbook TRIALS=3` (and llm modes with a key) → commit and inspect the CI run.
