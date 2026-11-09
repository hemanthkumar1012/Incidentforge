# IncidentForge: AI incident investigation and verified recovery

A controlled incident-response research platform. A small demo shop (checkout, inventory, payment simulator) emits
real telemetry; an incident lab injects **labelled synthetic faults**; an investigator (deterministic runbook or
Gemini) diagnoses them from that telemetry with read-only tools. It then proposes an allowlisted repair, which is
validated in an isolated sandbox, approved for the exact action by a second person, executed, and verified.

**Scope:** a known fault catalogue (currently one scenario, S1) on a demo system. Not an agent that fixes arbitrary
production systems.

> **Status: implementation complete for the core flow, runtime-unverified.** Nothing has run as a live stack in
> the development environment (no Docker, no package installs). See [PROJECT_STATUS.md](PROJECT_STATUS.md) for
> exactly what has run (PASS) and what has only been written (NOT RUN).

## Quick start

```bash
cp .env.example .env      # replace every change-me value (docs/operations.md#configuration-reference-env)
make up                   # build, migrate, seed, start, wait until ready
open http://localhost:3000
```

## Tests

```bash
pip install -r requirements/dev.txt
make test          # unit tests (no services)
make lint typecheck
TEST_ADMIN_DSN=postgresql://postgres:<pw>@localhost:5432/postgres make test-db   # PostgreSQL integration tests
cd web && npm install && npm run lint && npm run typecheck && npm test && npm run build
make up && make acceptance && make sandbox-check && make e2e    # stack-level, runbook mode
GEMINI_API_KEY=... make live-smoke   # optional; runbook acceptance does NOT verify Gemini
```

## Demo

`make reset && make journey && make inject-S1 && make load`, then follow the walkthrough in
[docs/operations.md](docs/operations.md#demo-walkthrough-about-10-minutes). Evaluation: `make evaluate`.

## Documentation

| Topic | Document |
|---|---|
| Setup, configuration, API examples, demo, reset, troubleshooting | [docs/operations.md](docs/operations.md) |
| Architecture and design decisions | [docs/architecture.md](docs/architecture.md) |
| Control-plane modules, transactions, jobs, retries, concurrency | [docs/backend-guide.md](docs/backend-guide.md) |
| State machines (diagrams) | [docs/states.md](docs/states.md) |
| Checkout idempotency contract | [docs/checkout-contract.md](docs/checkout-contract.md) |
| Threat model, authn/authz, access boundary, sandbox | [docs/security.md](docs/security.md) |
| Fault scenarios | [docs/scenarios.md](docs/scenarios.md) |
| Evaluation methodology | [docs/evaluation.md](docs/evaluation.md) |
| Requirements → tests matrix | [docs/requirements-tests.md](docs/requirements-tests.md) |
| Known issues and limitations | [docs/known-issues.md](docs/known-issues.md) |
| Dependency versions | [docs/dependencies.md](docs/dependencies.md) |
