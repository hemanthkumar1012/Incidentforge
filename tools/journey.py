#!/usr/bin/env python3
"""Automated checkout journey (synthetic). Stdlib only, so it runs anywhere.

    python3 tools/journey.py                         # expect success
    python3 tools/journey.py --expect failure        # expect checkout to fail
    python3 tools/journey.py --card tok_test_decline --expect declined

Steps: health -> list products -> checkout -> fetch order -> assert outcome.
Prints one JSON summary line; exit code 0 iff the observed outcome matches
--expect.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


def call(
    method: str, url: str, body: Any = None, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> tuple[int, dict[str, Any], dict[str, str], float]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})}
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status, raw, hdrs = resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        status, raw, hdrs = exc.code, exc.read(), dict(exc.headers)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return 0, {"error": {"code": "unreachable", "message": str(exc)}}, {}, time.perf_counter() - start
    elapsed = time.perf_counter() - start
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw[:200].decode(errors="replace")}
    return status, payload, hdrs, elapsed


def run(base: str, card: str) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    headers = {"X-Synthetic": "1", "X-Request-ID": f"journey-{run_id}"}
    result: dict[str, Any] = {"run_id": run_id, "synthetic": True, "steps": []}

    def step(name: str, status: int, elapsed: float, **extra: Any) -> None:
        result["steps"].append({"step": name, "status": status, "ms": round(elapsed * 1000, 1), **extra})

    status, _, _, t = call("GET", f"{base}/health", headers=headers)
    step("health", status, t)
    if status != 200:
        result["outcome"] = "unreachable"
        return result

    status, products, _, t = call("GET", f"{base}/api/products", headers=headers)
    step("products", status, t)
    in_stock = [p for p in products.get("products", []) if p.get("stock", 0) >= 2]
    if status != 200 or len(in_stock) < 2:
        result["outcome"] = "catalogue_unavailable"
        return result

    cart = [{"sku": in_stock[0]["sku"], "qty": 1}, {"sku": in_stock[1]["sku"], "qty": 2}]
    status, body, hdrs, t = call(
        "POST",
        f"{base}/api/checkout",
        body={"customer_id": f"synthetic-journey-{run_id}", "items": cart, "card_token": card},
        headers={**headers, "Idempotency-Key": f"journey-{run_id}"},
    )
    step(
        "checkout",
        status,
        t,
        request_id=hdrs.get("X-Request-ID"),
        error_code=(body.get("error") or {}).get("code"),
    )
    if status == 402:
        result["outcome"] = "declined"
        return result
    if status not in (200, 201):
        result["outcome"] = "failure"
        return result

    order_ref = body["order_ref"]
    status, order, _, t = call("GET", f"{base}/api/orders/{order_ref}", headers=headers)
    step("order_lookup", status, t, order_ref=order_ref, order_status=order.get("status"))
    result["order_ref"] = order_ref
    result["outcome"] = "success" if status == 200 and order.get("status") == "confirmed" else "failure"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--card", default="tok_test_visa")
    ap.add_argument("--expect", choices=["success", "failure", "declined"], default="success")
    args = ap.parse_args()
    result = run(args.base_url.rstrip("/"), args.card)
    result["expected"] = args.expect
    result["matched"] = result["outcome"] == args.expect
    print(json.dumps(result))
    return 0 if result["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
