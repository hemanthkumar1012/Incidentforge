# Deploying IncidentForge with Supabase and Vercel

## What can and cannot run where

IncidentForge is more than a web app and a database. The worker, the demo shop, the incident lab, the
isolated validation sandbox and the Prometheus/Loki/Jaeger stack are long-running containers on private
networks. Vercel runs short-lived functions and static files, and Supabase is a managed Postgres, so they
cannot host those. The split that works:

| Component | Where | Why |
|---|---|---|
| React dashboard (`web/`) | Vercel | static build |
| `/api/*` forwarder (`web/api/`) | Vercel function | same-origin to the browser, so the CSP stays `connect-src 'self'` and no CORS is needed |
| Control-plane DB (`forge` schema) | Supabase Postgres | managed, backed up |
| forge-api, forge-worker, shop, lab, sandbox, Postgres for shop/lab/validation, Prometheus, Loki, Jaeger | one container host (any Linux VM with Docker Compose) | needs private networks, `FOR UPDATE SKIP LOCKED` workers, and the sandbox boundary |
| TLS in front of forge-api | Caddy (in `docker-compose.prod.yml`) | automatic certificates |

The shop/lab databases and the isolated validation database deliberately stay off Supabase: they hold
ground truth and the sandbox boundary depends on separate roles and networks.

## Steps

1. **Supabase** (one project, region near the container host).
   1. Run `deploy/supabase/bootstrap.sql` as `postgres` (SQL editor or `psql -v forge_pw="'...'"`). This creates the
      private `forge` schema and the `forge_app` role.
   2. Build the URL from the Connect panel: session pooler, port 5432, user `forge_app.<project-ref>`,
      `sslmode=require`. Put it in `.env.production` as `SUPABASE_FORGE_DATABASE_URL`.
   3. Do **not** add `forge` to the Data API's exposed schemas.
2. **Container host.** Copy `.env.production.example` to `.env.production`, fill it in, point `API_DOMAIN` DNS at the host, then:
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d --build`.
   The `forge-migrate` service creates the tables in Supabase.
3. **Harden.** After migrations, run `deploy/supabase/harden.sql` and then `deploy/supabase/verify.sql` as `postgres`;
   every row of `verify.sql` must say `t`. Re-run `harden.sql` after any migration that adds tables.
4. **Vercel.** Import the repo, set **Root Directory** to `web`, and add the environment variable
   `API_ORIGIN=https://<API_DOMAIN>` (https is enforced for production deployments). Deploy.
5. Sign in with a bootstrap user and open Overview. A red "cannot reach the API" state means `API_ORIGIN`,
   DNS or the container host is wrong; the proxy returns a generic 502/503 and logs nothing sensitive.

## Security notes

- Only `/api/*` is forwarded by Vercel and published by Caddy; `/docs` and `/openapi.json` are not exposed.
- Login is throttled per username and globally (5 failures / 5 minutes per user). State is in process memory, so run **one**
  forge-api replica. The client IP is not used because behind the proxy it is not trustworthy.
- The API is reachable from the internet at `API_DOMAIN`, not only from Vercel (Vercel has no fixed egress IPs). Authentication,
  roles and exact-action approval are what protect it. Do not weaken them to make a demo pass.
- The session token lives in browser memory only; reloading the page signs you out by design.
- Rotate `FORGE_JWT_SECRET` and the bootstrap passwords before exposing the host.

## Verification status (what was and was not run)

| Check | Status | Evidence |
|---|---|---|
| API proxy behaviour (8 cases: forwarding, traversal, redirects, size cap, 502) | PASS | `cd web && npm run test:api` (node:test, local HTTP server) |
| `vercel.json` is valid JSON | PASS | parsed with Python `json` |
| Supabase bootstrap + DDL as `forge_app` lands in schema `forge`, none in `public` | PASS | throwaway local PG16, 11 tables |
| `harden.sql` idempotent; `verify.sql` all true after, one false before | PASS | same cluster |
| `anon`/`authenticated` denied; `forge_app` writes; audit UPDATE rejected | PASS | same cluster |
| Login throttle logic | PASS | `pytest tests/unit/forge/test_login_throttle.py` (5 tests) |
| Login route returns 429 + `Retry-After` | NOT RUN | needs FastAPI; test file skips without it, runs in CI |
| `docker-compose.prod.yml` merges cleanly, no internal ports published | PARTIAL | structural check only; `docker compose config` NOT RUN (no Docker here) |
| Behaviour on a real Supabase project (pooler username, `search_path` via pooler, advisors) | NOT RUN | no project was created; do this first and read `get_advisors` |
| Vercel build and function on a real deployment | NOT RUN | not deployed; frontend `npm run build` has also never been run |
| Caddy certificate issuance | NOT RUN | needs a real domain |
