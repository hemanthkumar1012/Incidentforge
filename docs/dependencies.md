# Dependency versions

Checked 2026-11-08 from public release listings where possible. The build
environment used to write Milestone 1 had no package-index access, so **these
pins have not yet been installed together**. The first `make up` (or the CI
`unit` job) is the compatibility check. If a pin fails to resolve, bump it to the
nearest available patch release and record the change here.

| Component | Pin | Source / confidence |
|---|---|---|
| Python | 3.13 (image `python:3.13-slim`) | verified locally (3.13) |
| FastAPI | 0.136.1 | pepy.tech lists 0.136.x as current (May 2026) |
| SQLAlchemy | 2.0.51 | sqlalchemy.org release post, June 2026 |
| Alembic | >=1.16,<2 | range; not individually verified |
| psycopg | >=3.2,<4 | range |
| httpx | >=0.28,<0.29 | range |
| uvicorn | 0.54.0 | version installed in the build environment |
| pydantic | >=2.11,<3 | 2.13.5 installed in the build environment |
| OpenTelemetry API/SDK/OTLP exporter | 1.45.0 | API 1.45.0 installed in the build environment; SDK pinned to match |
| OTel instrumentation (fastapi, httpx, sqlalchemy) | 0.66b0 | contrib releases pair 1.N with 0.(N+21)b0; not verified |
| prometheus-client | >=0.22,<1 | range |
| Postgres | `postgres:16-alpine` | matches local Postgres 16 used to test the init script |
| Prometheus | `prom/prometheus:v3.5.0` | v3.5 LTS line |
| Loki | `grafana/loki:3.7.9` | endoflife.date lists 3.7.9 (Oct 2026) |
| Jaeger | `jaegertracing/jaeger:2.20.0` | v2.20 referenced as current in Jaeger getting-started guides; also published as `cr.jaegertracing.io/jaegertracing/jaeger` |
