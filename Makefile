COMPOSE := docker compose
LAB := $(COMPOSE) --profile tools run --rm -T lab

.PHONY: help up down nuke ps logs reset journey journey-fail load inject-S1 lab-status lab-cleanup test acceptance lint

help:
	@echo "up | down | nuke | ps | logs | reset | journey | journey-fail | load | inject-S1 | lab-status | lab-cleanup | test | acceptance | lint"

up:            ## build, migrate, seed and start everything (waits for health)
	$(COMPOSE) up -d --build
	$(COMPOSE) --profile tools build lab
	python3 tools/wait_ready.py

down:
	$(COMPOSE) down

nuke:          ## stop and delete all data volumes
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100 checkout inventory payment

reset:         ## reset-to-healthy: clean up faults, restore baseline config, restock, verify
	$(LAB) reset

journey:       ## synthetic checkout journey, expecting success
	python3 tools/journey.py --expect success

journey-fail:
	python3 tools/journey.py --expect failure

load:          ## synthetic background load (Ctrl-C to stop)
	python3 tools/loadgen.py --rps $${LOAD_RPS:-3} --duration 0

inject-S1:     ## SYNTHETIC incident: incorrect payment endpoint
	$(LAB) inject S1

lab-status:
	$(LAB) status

lab-cleanup:
	$(LAB) cleanup

test:          ## unit tests (no running stack needed)
	python3 -m pytest tests/unit -q

acceptance:    ## Milestone 1 acceptance test against the running stack
	python3 scripts/m1_acceptance.py

lint:
	ruff check .

typecheck:     ## strict mypy on modules that do not need the service runtime (CI checks all of forge)
	python3 -m mypy forge shop lab

schema-probe:  ## forge DDL constraint probe against an EMPTY database (FORGE_PROBE_DSN)
	scripts/schema_probe.sh

test-db:       ## PostgreSQL integration tests (needs TEST_ADMIN_DSN superuser DSN and psql)
	python3 -m pytest tests/db -m db -q

e2e:           ## full product flow in runbook mode against the running stack (artifacts in artifacts/e2e)
	python3 scripts/e2e_flow.py

sandbox-check: ## runtime network-isolation probes from inside sandbox containers
	scripts/sandbox_isolation_check.sh

evaluate:      ## evaluation trials (MODES=runbook,llm_summary,llm TRIALS=3); results in artifacts/eval
	$(LAB) evaluate --modes $${MODES:-runbook} --trials $${TRIALS:-3}

live-smoke:    ## opt-in Gemini smoke test (needs GEMINI_API_KEY and network)
	python3 -m pytest tests/live -m live -q -s

web-dev:       ## UI dev server on :5173 proxying /api to :8080
	cd web && npm install && npm run dev
