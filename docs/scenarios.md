# Failure scenarios (Incident Lab)

All scenarios are **synthetic, injected incidents** against the demo shop.
Definitions live in `lab/scenarios/S*.yaml` and are validated by
`lab/scenarios.py`. This document is for humans; the investigator never sees
it, the scenario files, or the lab database.

Each scenario defines: injection procedure, cleanup procedure, private ground
truth, expected symptoms, supported recovery action, and recovery plus
regression verification checks.

| ID | Title | Split | Status |
|---|---|---|---|
| S1 | Incorrect payment-service endpoint | development | implemented (Milestone 1) |
| S2 | Slow inventory dependency | — | Milestone 4 (fault hook already exists) |
| S3 | Payment simulator returns controlled errors | — | Milestone 4 (fault hook already exists) |
| S4 | Invalid application configuration | — | Milestone 4 (`validate_config: false` path exists) |
| S5 | Constrained DB connection pool | — | Milestone 4, only if reliably reproducible |

## S1 — incorrect payment-service endpoint

- **Injection:** a new checkout config version changes `payment_url` from
  `http://payment:8002` to `http://payment:8020`. The change record uses neutral
  wording ("checkout config update", actor `release-pipeline`).
- **Why it is a good test:** the value passes schema validation (it is a
  well-formed URL), so it can only be found by correlating telemetry with change
  history. Payment itself stays healthy, which is the trap: a naive diagnosis
  blames the payment service.
- **Expected symptoms:** checkout 502 `dependency_unavailable`; `connect_error`
  outcomes toward `payment:8020`; payment request rate drops to about zero while
  its health stays OK; a checkout `config_change` event precedes the error onset;
  stock is unchanged because reservations are released.
- **Cleanup / reset:** restore the baseline config (skipped if already restored,
  for example by an approved rollback).
- **Supported recovery:** `rollback_config_version` on `checkout`.
- **Verification:** the journey succeeds and connect errors stop (recovery);
  inventory and payment are healthy and a declined card still returns 402 (regression).

## Commands

```bash
make inject-S1      # inject
make lab-status     # show injections (operator view, includes ACTIVE marker)
make lab-cleanup    # undo the active injection
make reset          # reset-to-healthy from any state, then verify readiness
```
