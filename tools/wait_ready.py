#!/usr/bin/env python3
"""Poll the stack's readiness endpoints until all are ready (stdlib only).

Checks checkout readiness (which itself requires DB + valid config) plus the
observability backends the investigator will query.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request

TARGETS = {
    "checkout": "http://localhost:8000/ready",
    "prometheus": "http://localhost:9090/-/ready",
    "loki": "http://localhost:3100/ready",
    "jaeger": "http://localhost:16686/",
    "forge-api": "http://localhost:8080/health",
}


def ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=180)
    args = ap.parse_args()
    deadline = time.monotonic() + args.timeout
    pending = dict(TARGETS)
    while pending and time.monotonic() < deadline:
        for name, url in list(pending.items()):
            if ready(url):
                print(f"[ready] {name}", file=sys.stderr)
                del pending[name]
        if pending:
            time.sleep(2)
    if pending:
        print(f"[not ready after {args.timeout:.0f}s] {', '.join(pending)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
