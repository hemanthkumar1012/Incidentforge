"""Time-series panels for the dashboard.

The queries are fixed here, on the server. The browser only chooses a panel id and a window from a short allowlist,
so no query text from a client ever reaches Prometheus. Every query is also run through the investigator's PromQL
guard (see tests), which keeps the dashboard on the same metric allowlist as the investigator.

Each panel is fetched independently: a failing panel reports its own error and the others still render.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from forge.telemetry.ports import MetricsBackend, TelemetryUnavailable

WINDOWS_MINUTES = (15, 60, 360)
TARGET_POINTS = 60
MIN_STEP_S = 15
MAX_SERIES = 8
MAX_POINTS = 400
MAX_ANNOTATIONS = 30
LABEL_CHARS = 80


@dataclass(frozen=True)
class Panel:
    id: str
    title: str
    unit: str
    query: str
    label_keys: tuple[str, ...]


PANELS: tuple[Panel, ...] = (
    Panel(
        "order_outcomes",
        "Checkout orders by status",
        "orders/s",
        "sum by (status) (rate(shop_checkout_orders_total[1m]))",
        ("status",),
    ),
    Panel(
        "request_rate",
        "Inbound requests",
        "req/s",
        "sum by (service) (rate(shop_http_requests_total[1m]))",
        ("service",),
    ),
    Panel(
        "server_errors",
        "Inbound 5xx responses",
        "req/s",
        'sum by (service) (rate(shop_http_requests_total{status=~"5.."}[1m]))',
        ("service",),
    ),
    Panel(
        "p95_latency",
        "p95 inbound latency",
        "s",
        "histogram_quantile(0.95, sum by (service, le) (rate(shop_http_request_duration_seconds_bucket[1m])))",
        ("service",),
    ),
    Panel(
        "dependency_failures",
        "Failed dependency calls",
        "calls/s",
        'sum by (service, dependency, outcome) (rate(shop_dependency_requests_total{outcome!="success"}[1m]))',
        ("service", "dependency", "outcome"),
    ),
)
PANEL_IDS = tuple(p.id for p in PANELS)


def step_for(window_minutes: int) -> int:
    return max(MIN_STEP_S, (window_minutes * 60) // TARGET_POINTS)


def _number(raw: Any) -> float | None:
    """Prometheus sends numbers as strings, and NaN for undefined values such as a quantile with no traffic."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _label(labels: dict[str, str], keys: tuple[str, ...]) -> str:
    parts = [labels[k] for k in keys if labels.get(k)]
    return " / ".join(parts) if parts else "total"


def shape_series(raw: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    built: list[tuple[float, dict[str, Any]]] = []
    for r in raw:
        points: list[list[float | None]] = [[float(ts), _number(v)] for ts, v in r.get("values", [])][-MAX_POINTS:]
        peak = max((p[1] for p in points if p[1] is not None), default=0.0)
        built.append((peak, {"label": _label(r.get("labels", {}), keys), "points": points}))
    # Busiest series first so the cap drops the least interesting ones.
    built.sort(key=lambda item: -item[0])
    return [series for _, series in built[:MAX_SERIES]]


def fetch_panel(backend: MetricsBackend, panel: Panel, window_minutes: int, now: datetime) -> dict[str, Any]:
    base: dict[str, Any] = {"id": panel.id, "title": panel.title, "unit": panel.unit, "series": [], "error": None}
    try:
        raw = backend.query_range(panel.query, now - timedelta(minutes=window_minutes), now, step_for(window_minutes))
    except TelemetryUnavailable as exc:
        return {**base, "error": str(exc)}
    return {**base, "series": shape_series(raw, panel.label_keys)}


def fetch_dashboard(
    backend: MetricsBackend,
    window_minutes: int,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    annotate: Callable[[datetime, datetime], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if window_minutes not in WINDOWS_MINUTES:
        raise ValueError(f"window must be one of {WINDOWS_MINUTES}")
    stamp = now()
    with ThreadPoolExecutor(max_workers=len(PANELS)) as pool:
        panels = list(pool.map(lambda p: fetch_panel(backend, p, window_minutes, stamp), PANELS))
    annotations: list[dict[str, Any]] = []
    annotations_error: str | None = None
    if annotate:
        try:
            annotations = annotate(stamp - timedelta(minutes=window_minutes), stamp)
        except TelemetryUnavailable as exc:  # the charts are still useful without the event markers
            annotations_error = str(exc)
    return {
        "window_minutes": window_minutes,
        "step_s": step_for(window_minutes),
        "generated_at": stamp.isoformat(),
        "panels": panels,
        "annotations": annotations,
        "annotations_error": annotations_error,
    }


def _as_utc(value: datetime | str) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_annotations(
    config_versions: list[dict[str, Any]],
    incidents: list[tuple[str, str, datetime]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Events that happened inside the chart window: configuration changes and incidents opening.

    Both come from the control plane's own records, so a spike on a chart can be read against what changed.
    Labels contain author names and incident titles; the UI renders them as text only.
    """
    found: list[dict[str, Any]] = []
    for row in config_versions:
        at = _as_utc(row.get("created_at", ""))
        if at and start <= at <= end:
            found.append(
                {
                    "ts": at.timestamp(),
                    "kind": "config_change",
                    "ref": str(row["version"]),
                    "label": f"Checkout config v{row['version']} by {row.get('author', 'unknown')}"[:LABEL_CHARS],
                }
            )
    for incident_id, title, opened in incidents:
        at = _as_utc(opened)
        if at and start <= at <= end:
            found.append(
                {
                    "ts": at.timestamp(),
                    "kind": "incident",
                    "ref": incident_id,
                    "label": f"Incident opened: {title}"[:LABEL_CHARS],
                }
            )
    found.sort(key=lambda a: a["ts"])
    return found[-MAX_ANNOTATIONS:]
