"""Incident detection rule (pure; used by forge/jobs/detector.py)."""

from __future__ import annotations

from typing import Any

MIN_FAILURE_RATIO = 0.2


def evaluate(series: list[dict[str, Any]], min_failures: float) -> dict[str, Any] | None:
    """Return the signal if the threshold is crossed, else None (pure, unit-tested)."""
    totals: dict[str, float] = {}
    for s in series:
        values = [float(v[1]) for v in s.get("values", []) if v[1] not in ("NaN",)]
        if values:
            totals[s.get("labels", {}).get("status", "unknown")] = values[-1]
    failed, confirmed = totals.get("failed", 0.0), totals.get("confirmed", 0.0)
    attempts = failed + confirmed
    if failed < min_failures or attempts == 0 or failed / attempts < MIN_FAILURE_RATIO:
        return None
    return {
        "metric": "shop_checkout_orders_total",
        "window": "5m",
        "failed": round(failed, 1),
        "confirmed": round(confirmed, 1),
        "failure_ratio": round(failed / attempts, 3),
    }
