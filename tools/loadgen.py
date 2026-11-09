#!/usr/bin/env python3
"""Synthetic load generator for the demo shop. Stdlib only.

All traffic is labelled synthetic (X-Synthetic: 1, customer ids
``synthetic-*``). A small share of requests uses the decline test card so the
baseline contains realistic, non-incident 402 responses.

    python3 tools/loadgen.py --rps 5 --duration 300
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

SKUS = [f"SKU-100{i}" for i in range(1, 9)]


def one_checkout(base: str, rng: random.Random, decline_ratio: float, timeout: float) -> str:
    items = [{"sku": s, "qty": rng.randint(1, 2)} for s in rng.sample(SKUS, rng.randint(1, 3))]
    card = "tok_test_decline" if rng.random() < decline_ratio else "tok_test_visa"
    body = json.dumps(
        {"customer_id": f"synthetic-{rng.randint(1, 500):04d}", "items": items, "card_token": card}
    ).encode()
    req = urllib.request.Request(
        f"{base}/api/checkout",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Synthetic": "1",
            "Idempotency-Key": "load-" + uuid.uuid4().hex,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return str(resp.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return "unreachable"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--rps", type=float, default=3.0)
    ap.add_argument("--duration", type=float, default=60.0, help="seconds; 0 = run until Ctrl-C")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--decline-ratio", type=float, default=0.02)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if not 0 < args.rps <= 200:
        ap.error("--rps must be in (0, 200]")

    base = args.base_url.rstrip("/")
    counts: collections.Counter[str] = collections.Counter()
    lock = threading.Lock()
    sem = threading.Semaphore(args.workers)
    master = random.Random(args.seed)
    stop_at = time.monotonic() + args.duration if args.duration > 0 else float("inf")
    interval = 1.0 / args.rps
    last_report = time.monotonic()
    print(f"[loadgen] SYNTHETIC load: {args.rps} rps against {base}", file=sys.stderr)

    def worker(seed: int) -> None:
        try:
            status = one_checkout(base, random.Random(seed), args.decline_ratio, args.timeout)
            with lock:
                counts[status] += 1
        finally:
            sem.release()

    try:
        next_at = time.monotonic()
        while time.monotonic() < stop_at:
            if not sem.acquire(timeout=1):
                with lock:
                    counts["skipped_backpressure"] += 1
                continue
            threading.Thread(target=worker, args=(master.getrandbits(32),), daemon=True).start()
            next_at += interval
            time.sleep(max(0.0, next_at - time.monotonic()))
            if time.monotonic() - last_report >= 10:
                last_report = time.monotonic()
                with lock:
                    print(f"[loadgen] {dict(counts)}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    for _ in range(args.workers):  # wait for in-flight requests
        sem.acquire(timeout=args.timeout)
    print(json.dumps({"synthetic": True, "counts": dict(counts)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
