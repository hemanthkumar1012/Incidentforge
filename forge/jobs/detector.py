"""Threshold incident detector.

Deliberately simple and explainable: if failed checkouts in the last 5 minutes
exceed ``DETECTOR_MIN_FAILURES`` *and* make up at least ``MIN_FAILURE_RATIO`` of
attempts, open a detector incident. The database's partial unique index
guarantees at most one open detector incident, so repeated detections are no-ops.
The detector only registers incidents; it never starts investigations or actions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from forge.domain.detection import evaluate
from forge.services import incidents
from forge.telemetry.ports import TelemetryUnavailable

if TYPE_CHECKING:
    from forge.wiring import Container

log = logging.getLogger("forge.detector")
QUERY = "sum by (status) (increase(shop_checkout_orders_total[5m]))"


def run_once(c: Container) -> str | None:
    end = datetime.now(UTC)
    try:
        series = c.prometheus.query_range(QUERY, end - timedelta(minutes=1), end, 30)
    except TelemetryUnavailable as exc:
        log.warning("detector skipped: %s", exc)
        return None
    signal = evaluate(series, c.settings.detector_min_failures)
    if signal is None:
        return None
    with c.sessions.begin() as s:
        incident = incidents.register_detected(
            s,
            title=f"Checkout failure ratio {signal['failure_ratio']:.0%} over 5m",
            severity="sev2",
            signal=signal,
        )
        return incident.id if incident else None
