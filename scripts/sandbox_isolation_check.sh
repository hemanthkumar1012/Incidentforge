#!/usr/bin/env bash
# Runtime verification of the validation sandbox's network boundary (run after `make up`).
# Each probe runs *inside* a sandbox container, so it tests what the sandbox can actually reach.
#   PASS lines = expected outcome; exits non-zero on any unexpected result.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
probe() { # probe expect(reach|blocked) container host port
  local out
  out=$(docker compose exec -T "$2" python -c "
import socket,sys
try:
    socket.create_connection(('$3', $4), timeout=3).close(); print('reach')
except OSError as e:
    print('blocked', type(e).__name__)" 2>&1 | tail -1)
  if [[ "$out" == "$1"* ]]; then echo "PASS  $2 -> $3:$4 ($out)"; else echo "FAIL  $2 -> $3:$4 expected $1, got: $out"; fail=1; fi
}
# required sandbox dependencies
probe reach   sandbox-checkout sandbox-payment   8002
probe reach   sandbox-checkout sandbox-inventory 8001
probe reach   sandbox-checkout postgres          5432
# production services and the outside world must be unreachable
probe blocked sandbox-checkout checkout   8000
probe blocked sandbox-checkout payment    8002
probe blocked sandbox-checkout inventory  8001
probe blocked sandbox-checkout forge-api  8080
probe blocked sandbox-checkout 1.1.1.1    443
probe blocked sandbox-inventory payment   8002
# sandbox credentials cannot open the production shop database
if docker compose exec -T sandbox-checkout python -c "
import os, psycopg; u=os.environ['SHOP_DATABASE_URL'].replace('+psycopg','').replace('/shop_validation','/shop')
psycopg.connect(u, connect_timeout=3)" >/dev/null 2>&1; then
  echo "FAIL  sandbox credentials connected to production shop DB"; fail=1
else echo "PASS  sandbox credentials refused by production shop DB"; fi
exit $fail
