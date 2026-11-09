# Operations: setup, configuration, API usage, demo, reset, troubleshooting

## Setup from a fresh checkout

```bash
git clone <repo> incidentforge && cd incidentforge
cp .env.example .env
# Replace every change-me value. Generate secrets with:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
make up            # builds images, migrates shop/forge/sandbox DBs, seeds, starts, waits for readiness
```

Requirements: Docker with Compose v2, ~3 GB free RAM, Python 3.10+ on the host (stdlib only for scripts),
Node 22 only for UI development. UI: http://localhost:3000 · API docs: http://localhost:8080/docs ·
shop: http://localhost:8000 · Jaeger: http://localhost:16686 · Prometheus: http://localhost:9090.

## Configuration reference (.env)

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD`, `*_DB_PASSWORD` | one password per DB role (shop, lab, forge, forge_reader, forge_remediator, sandbox) |
| `LAB_ADMIN_TOKEN`, `SANDBOX_ADMIN_TOKEN` | fault/admin hooks in production shop vs sandbox (never given to the investigator) |
| `FORGE_JWT_SECRET` | ≥ 32 chars; signs access tokens |
| `FORGE_BOOTSTRAP_USERS` | `name:role:password,...` created on first start (passwords ≥ 12 chars); demo only |
| `FORGE_DEFAULT_MODE` | `runbook` (default) or `llm` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | enable `llm` and `llm_summary` modes |
| `LLM_INPUT_USD_PER_MTOK`, `LLM_OUTPUT_USD_PER_MTOK` | prices for *estimated* cost |
| `DETECTOR_ENABLED`, `DETECTOR_MIN_FAILURES` | threshold detector (≥ N failed checkouts and ≥ 20% failure ratio over 5 min) |
| `EVAL_OPERATOR`, `EVAL_APPROVER` | `user:password` accounts the evaluator uses |
| `FORGE_CORS_ORIGINS` | normally empty (the UI is same-origin through its proxy) |

Keep `.env` out of version control (it is git-ignored). Use throwaway values; nothing here protects real data.

## API usage examples

```bash
TOKEN=$(curl -s localhost:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"olivia","password":"<operator password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"
curl -s -H "$H" -H 'Content-Type: application/json' localhost:8080/api/incidents -d '{"title":"Checkout errors","severity":"sev2"}'
curl -s -H "$H" -H 'Content-Type: application/json' localhost:8080/api/incidents/<inc_id>/investigations -d '{"mode":"runbook"}'
curl -s -H "$H" localhost:8080/api/investigations/<inv_id>            # steps + evidence + diagnosis
curl -s -H "$H" localhost:8080/api/incidents/<inc_id>                 # workspace snapshot incl. proposal
curl -s -H "$H" -X POST localhost:8080/api/proposals/<prop_id>/validations
curl -s -H "$H" -X POST localhost:8080/api/proposals/<prop_id>/approvals     # returns binding_digest
# as a different user with the approver role:
curl -s -H "Authorization: Bearer $APPROVER_TOKEN" -H 'Content-Type: application/json' \
  localhost:8080/api/approvals/<apr_id>/decision -d '{"approve":true,"note":"diff verified","binding_digest":"<digest>"}'
curl -s -H "$H" -X POST localhost:8080/api/proposals/<prop_id>/recovery      # 202 first time, 200 + same job after
```

Errors are always `{"error": {"code", "message", "details"}}` with 401/403/404/409/412/422.

## Demo walkthrough (about 10 minutes)

1. `make up`, open http://localhost:3000, sign in as the operator. The **Overview** shows live readiness, service
   relationships and config history.
2. `make journey`: a successful synthetic checkout.
3. `make inject-S1`: the injected incident (a checkout config change pointing payment at the wrong port).
4. `make load` for a minute (or `make journey-fail` a few times). Within ~15 s of crossing the threshold the
   detector opens an incident in **Incidents**; you can also register one manually.
5. Open the incident, choose **runbook** (or **LLM** with a key) and start the investigation. Watch the timeline
   fill; click evidence IDs to open raw tool results.
6. Read the diagnosis: the caller-misconfiguration hypothesis ranks above "payment is down", which the readiness
   evidence contradicts.
7. In the action panel: **Validate in sandbox**, then **Request approval**.
8. Sign in as the approver (another browser profile, since the session is per tab): **Approvals** → review the exact
   diff and digest → approve with a note. Trying to approve as the requester is refused.
9. Back as the operator: **Execute approved action** → watch verification → the incident resolves.
10. `make journey` succeeds; the **Audit history** panel shows every step with actors and times.

## Reset and cleanup

```bash
make reset        # lab reset-to-healthy: clear faults, restore baseline config, restock, verify readiness
make down         # stop containers, keep data
make nuke         # stop and DELETE all volumes (all incidents, audit history, orders). Destructive.
rm -rf artifacts  # local test reports and evaluation outputs
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `make up` fails on a missing variable | compose names it; set it in `.env` |
| forge-api unhealthy | `docker compose logs forge-api`: `FORGE_JWT_SECRET` too short or a bootstrap password < 12 chars fails fast |
| Investigation stays `queued` | `docker compose logs forge-worker`; the worker must be running and reach postgres |
| Investigation `insufficient_evidence` with "required signals unavailable" | Prometheus/Loki/Jaeger health; the evidence panel shows the failing backend |
| Validation `error` | sandbox containers running? `make sandbox-check`; `docker compose logs sandbox-checkout` |
| Validation `not_reproducible` | the production failure was gone or not config-related; nothing was verified (expected for non-config faults) |
| Recovery `refused` | production config changed after approval; re-validate and re-approve |
| Detector never fires | needs ≥ `DETECTOR_MIN_FAILURES` failures *and* ≥ 20% ratio over 5 min; register manually instead |
| No traces in Jaeger | Jaeger v2 config keys are unverified (known issue O2); check `docker compose logs jaeger` |
| UI shows "Live updates failing" | API unreachable; data shown is the last good snapshot, retried with backoff |
| e2e failed | see `artifacts/e2e/report.json`, `api_responses.json`, `service_logs.txt` (secrets redacted) |
