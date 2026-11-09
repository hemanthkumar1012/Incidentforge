#!/usr/bin/env python3
"""Milestone 1 acceptance test against a running stack (stdlib only).

Precondition: `make up` has completed. Steps:

  1. reset-to-healthy via the lab
  2. checkout journey succeeds
  3. inject S1 (SYNTHETIC: incorrect payment endpoint)
  4. checkout journey fails with dependency_unavailable
  5. telemetry shows the fault: Prometheus connect_error counter, Loki error
     logs naming the target, Jaeger error traces for checkout, change event
  6. reset-to-healthy
  7. checkout journey succeeds again

Exit code 0 only if every check passes. Prints a JSON report.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = "http://localhost:8000"
PROM = "http://localhost:9090"
LOKI = "http://localhost:3100"
JAEGER = "http://localhost:16686"
CONFIG_TTL_WAIT_S = 5

report: dict[str, Any] = {"synthetic": True, "checks": []}


def check(name: str, ok: bool, **detail: Any) -> bool:
    report["checks"].append({"check": name, "ok": bool(ok), **detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(detail)[:300]}", file=sys.stderr)
    return ok


def sh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180)


def lab(*args: str) -> subprocess.CompletedProcess[str]:
    return sh("docker", "compose", "--profile", "tools", "run", "--rm", "-T", "lab", *args)


def journey(expect: str) -> dict[str, Any]:
    proc = sh(sys.executable, "tools/journey.py", "--base-url", CHECKOUT, "--expect", expect)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"matched": False, "stdout": proc.stdout[-300:], "stderr": proc.stderr[-300:]}


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read())


def prom_query(expr: str) -> float:
    data = get_json(f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
    result = data["data"]["result"]
    return sum(float(r["value"][1]) for r in result)


def poll(fn, timeout_s: float = 30, interval_s: float = 2):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout_s
    value = fn()
    while not value and time.monotonic() < deadline:
        time.sleep(interval_s)
        value = fn()
    return value


def main() -> int:
    r = lab("reset")
    check("lab reset (initial)", r.returncode == 0, stderr=r.stderr[-200:])

    j = journey("success")
    check("journey succeeds when healthy", j.get("matched", False), outcome=j.get("outcome"))

    injected_at = time.time()
    r = lab("inject", "S1")
    check("inject S1 (synthetic)", r.returncode == 0, stdout=r.stdout[-200:], stderr=r.stderr[-200:])
    time.sleep(CONFIG_TTL_WAIT_S)

    j = journey("failure")
    codes = [s.get("error_code") for s in j.get("steps", []) if s.get("step") == "checkout"]
    check("journey fails after injection", j.get("matched", False), error_codes=codes)
    check("failure is dependency_unavailable", codes == ["dependency_unavailable"], error_codes=codes)

    connect_errors = poll(
        lambda: prom_query('sum(shop_dependency_requests_total{dependency="payment",outcome="connect_error"})')
    )
    check("prometheus: payment connect_error counter > 0", connect_errors > 0, value=connect_errors)

    def loki_hits() -> int:
        q = '{service="checkout"} |= "dependency call failed" | json | fields_target="payment:8020"'
        params = {"query": q, "start": str(int((injected_at - 5) * 1e9)), "limit": "20"}
        data = get_json(f"{LOKI}/loki/api/v1/query_range?" + urllib.parse.urlencode(params))
        return sum(len(s["values"]) for s in data["data"]["result"])

    hits = poll(loki_hits)
    check("loki: error logs name the wrong target payment:8020", hits > 0, lines=hits)

    def jaeger_errors() -> int:
        params = {
            "service": "checkout",
            "limit": "20",
            "lookback": "15m",
            "tags": json.dumps({"error": "true"}),
        }
        data = get_json(f"{JAEGER}/api/traces?" + urllib.parse.urlencode(params))
        return len(data.get("data") or [])

    traces = poll(jaeger_errors)
    check("jaeger: checkout traces with errors exist", traces > 0, traces=traces)

    r = lab("reset")
    check("lab reset (recovery)", r.returncode == 0, stderr=r.stderr[-200:])
    time.sleep(CONFIG_TTL_WAIT_S)
    j = journey("success")
    check("journey succeeds after reset", j.get("matched", False), outcome=j.get("outcome"))

    report["passed"] = all(c["ok"] for c in report["checks"])
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
