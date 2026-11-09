"""The investigator's read-only tools.

Each tool is an input model (validation + bounds) and a handler that queries
one telemetry port and shapes the result into a compact, model-friendly form.
Handlers never build queries from unvalidated strings: LogQL is assembled
server-side from typed fields, PromQL passes ``check_promql``, and network
diagnostics only reach endpoints that appear in the shop's own configuration.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forge.investigation.promql import PromQLRejected, check_promql
from forge.investigation.toolkit import ToolError, ToolRegistry, ToolSpec
from forge.telemetry.ports import (
    ChangeHistory,
    Diagnostics,
    LogsBackend,
    MetricsBackend,
    TelemetryUnavailable,
    TracesBackend,
)
from shop.common.config_schema import config_diff

Service = Literal["checkout", "inventory", "payment"]
SERVICES: tuple[str, ...] = ("checkout", "inventory", "payment")
STATIC_TOPOLOGY = {"checkout": ["inventory", "payment", "postgres"], "inventory": ["postgres"], "payment": []}
SPAN_ATTRIBUTE_ALLOWLIST = (
    "http.request.method",
    "http.method",
    "http.route",
    "http.response.status_code",
    "http.status_code",
    "url.full",
    "http.url",
    "server.address",
    "server.port",
    "error.type",
    "exception.type",
    "exception.message",
    "shop.request_id",
    "db.system",
    "db.operation",
)

SCOPE_TELEMETRY = "telemetry:read"
SCOPE_CHANGES = "changes:read"
SCOPE_DIAGNOSTICS = "diagnostics:run"
INVESTIGATOR_SCOPES = frozenset({SCOPE_TELEMETRY, SCOPE_CHANGES, SCOPE_DIAGNOSTICS})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryMetricsInput(_Input):
    query: str = Field(
        description="PromQL over shop_* metrics, e.g. sum by (outcome) (rate(shop_dependency_requests_total[5m]))"
    )
    window_minutes: int = Field(default=15, ge=1, le=60)
    step_seconds: int = Field(default=30, ge=15, le=300)

    @field_validator("query")
    @classmethod
    def _promql(cls, v: str) -> str:
        try:
            return check_promql(v)
        except PromQLRejected as exc:
            raise ValueError(str(exc)) from exc


class SearchLogsInput(_Input):
    service: Service
    contains: str | None = Field(default=None, max_length=100, description="case-sensitive substring")
    level: Literal["error", "warning", "info"] | None = None
    window_minutes: int = Field(default=15, ge=1, le=60)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("contains")
    @classmethod
    def _no_backtick(cls, v: str | None) -> str | None:
        if v is not None and ("`" in v or "\n" in v):
            raise ValueError("contains must not include backticks or newlines")
        return v


class FindTracesInput(_Input):
    service: Service
    errors_only: bool = True
    window_minutes: int = Field(default=15, ge=1, le=60)
    limit: int = Field(default=10, ge=1, le=20)
    min_duration_ms: int | None = Field(default=None, ge=1, le=60_000)


class GetTraceInput(_Input):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class NoInput(_Input):
    pass


class GetRecentChangesInput(_Input):
    service: Service | None = None
    window_hours: int = Field(default=6, ge=1, le=24)
    limit: int = Field(default=20, ge=1, le=50)


class GetConfigurationDiffInput(_Input):
    service: Literal["checkout"] = "checkout"
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)


class RunDiagnosticInput(_Input):
    name: Literal["service_readiness", "tcp_connect_configured_endpoints"]


def _summarise_series(series: list[dict[str, Any]], max_series: int = 30) -> list[dict[str, Any]]:
    out = []
    for s in series[:max_series]:
        values = [float(v[1]) for v in s.get("values", []) if v[1] not in ("NaN", "+Inf", "-Inf")]
        if not values:
            continue
        out.append(
            {
                "labels": s.get("labels", {}),
                "last": round(values[-1], 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "avg": round(sum(values) / len(values), 4),
                "points": len(values),
            }
        )
    return out


def _parse_log_line(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        doc = json.loads(entry["line"])
    except (json.JSONDecodeError, TypeError):
        return {"ts": entry.get("ts"), "raw": str(entry.get("line", ""))[:500]}
    keep = ("ts", "level", "service", "msg", "request_id", "trace_id", "fields", "synthetic")
    return {k: doc[k] for k in keep if k in doc}


def _endpoint(url: str) -> tuple[str, int] | None:
    parts = urlsplit(url)
    if not parts.hostname:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    return parts.hostname, port


class _Handlers:
    def __init__(
        self,
        metrics: MetricsBackend,
        logs: LogsBackend,
        traces: TracesBackend,
        changes: ChangeHistory,
        diagnostics: Diagnostics,
        clock: Callable[[], datetime],
    ) -> None:
        self.metrics, self.logs, self.traces = metrics, logs, traces
        self.changes, self.diagnostics, self.clock = changes, diagnostics, clock

    def _window(self, minutes: int) -> tuple[datetime, datetime]:
        end = self.clock()
        return end - timedelta(minutes=minutes), end

    def query_metrics(self, a: QueryMetricsInput) -> dict[str, Any]:
        start, end = self._window(a.window_minutes)
        series = _backend(lambda: self.metrics.query_range(a.query, start, end, a.step_seconds))
        return {
            "query": a.query,
            "window_minutes": a.window_minutes,
            "series_count": len(series),
            "series": _summarise_series(series),
        }

    def search_logs(self, a: SearchLogsInput) -> dict[str, Any]:
        selector = f'{{service="{a.service}"' + (f', level="{a.level}"' if a.level else "") + "}"
        logql = selector + (f" |= `{a.contains}`" if a.contains else "")
        start, end = self._window(a.window_minutes)
        lines = _backend(lambda: self.logs.query(logql, start, end, a.limit))
        return {"logql": logql, "count": len(lines), "lines": [_parse_log_line(e) for e in lines]}

    def find_traces(self, a: FindTracesInput) -> dict[str, Any]:
        start, end = self._window(a.window_minutes)
        found = _backend(
            lambda: self.traces.find(
                a.service,
                errors_only=a.errors_only,
                start=start,
                end=end,
                limit=a.limit,
                min_duration_ms=a.min_duration_ms,
            )
        )
        return {"count": len(found), "traces": found}

    def get_trace(self, a: GetTraceInput) -> dict[str, Any]:
        trace = _backend(lambda: self.traces.get(a.trace_id))
        if trace is None:
            raise ToolError("not_found", f"trace {a.trace_id} not found (it may have aged out)")
        spans = []
        for span in trace.get("spans", [])[:100]:
            attrs = span.get("attributes", {})
            spans.append(
                {
                    **{k: v for k, v in span.items() if k != "attributes"},
                    "attributes": {k: attrs[k] for k in SPAN_ATTRIBUTE_ALLOWLIST if k in attrs},
                }
            )
        return {"trace_id": a.trace_id, "span_count": len(trace.get("spans", [])), "spans": spans}

    def get_service_dependencies(self, _: NoInput) -> dict[str, Any]:
        start, end = self._window(15)
        observed = _backend(
            lambda: self.metrics.query_range(
                "sum by (service, dependency, outcome) (increase(shop_dependency_requests_total[15m]))",
                start,
                end,
                60,
            )
        )
        active = _backend(lambda: self.changes.active("checkout")) or {}
        payload = active.get("payload", {})
        return {
            "static_topology": STATIC_TOPOLOGY,
            "configured_endpoints": {
                "checkout": {k: v for k, v in payload.items() if k.endswith("_url")},
                "config_version": active.get("version"),
            },
            "observed_calls_15m": _summarise_series(observed),
        }

    def get_recent_changes(self, a: GetRecentChangesInput) -> dict[str, Any]:
        since = self.clock() - timedelta(hours=a.window_hours)
        events = _backend(lambda: self.changes.recent(a.service, since, a.limit))
        return {"window_hours": a.window_hours, "count": len(events), "changes": events}

    def get_configuration_diff(self, a: GetConfigurationDiffInput) -> dict[str, Any]:
        old = _backend(lambda: self.changes.version(a.service, a.from_version))
        new = _backend(lambda: self.changes.version(a.service, a.to_version))
        missing = [v for v, row in ((a.from_version, old), (a.to_version, new)) if row is None]
        if missing or old is None or new is None:
            raise ToolError("not_found", f"{a.service} has no config version(s) {missing}")
        return {
            "service": a.service,
            "from_version": a.from_version,
            "to_version": a.to_version,
            "changes": config_diff(old["payload"], new["payload"]),
            "to_version_author": new.get("author"),
            "to_version_created_at": new.get("created_at"),
        }

    def run_allowlisted_diagnostic(self, a: RunDiagnosticInput) -> dict[str, Any]:
        if a.name == "service_readiness":
            readiness: dict[str, Any] = {}
            for service in SERVICES:
                readiness[service] = _backend(partial(self.diagnostics.readiness, service))
            return {"diagnostic": a.name, "results": readiness}
        active = _backend(partial(self.changes.active, "checkout")) or {}
        results: dict[str, Any] = {}
        for key, url in sorted(active.get("payload", {}).items()):
            if not key.endswith("_url"):
                continue
            endpoint = _endpoint(str(url))
            if endpoint is None:
                results[key] = {"url": url, "reachable": False, "error": "unparseable URL"}
            else:
                results[key] = {"url": url, **_backend(partial(self.diagnostics.tcp_connect, *endpoint))}
        return {"diagnostic": a.name, "config_version": active.get("version"), "results": results}


def _backend(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except TelemetryUnavailable as exc:
        raise ToolError("backend_unavailable", str(exc), retryable=True) from exc


def build_registry(
    metrics: MetricsBackend,
    logs: LogsBackend,
    traces: TracesBackend,
    changes: ChangeHistory,
    diagnostics: Diagnostics,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ToolRegistry:
    h = _Handlers(metrics, logs, traces, changes, diagnostics, clock)
    return ToolRegistry(
        [
            ToolSpec(
                "query_metrics",
                "Run a bounded PromQL range query over shop_* metrics; returns per-series last/min/max/avg.",
                QueryMetricsInput,
                SCOPE_TELEMETRY,
                h.query_metrics,
            ),
            ToolSpec(
                "search_logs",
                "Search one service's structured logs by level and substring.",
                SearchLogsInput,
                SCOPE_TELEMETRY,
                h.search_logs,
            ),
            ToolSpec(
                "find_traces",
                "List recent traces for a service, optionally only errored ones.",
                FindTracesInput,
                SCOPE_TELEMETRY,
                h.find_traces,
            ),
            ToolSpec(
                "get_trace",
                "Fetch the spans of one trace (allowlisted attributes only).",
                GetTraceInput,
                SCOPE_TELEMETRY,
                h.get_trace,
            ),
            ToolSpec(
                "get_service_dependencies",
                "Static topology, configured endpoints and observed call outcomes between services.",
                NoInput,
                SCOPE_TELEMETRY,
                h.get_service_dependencies,
            ),
            ToolSpec(
                "get_recent_changes",
                "Recent config changes/deploys from the change log.",
                GetRecentChangesInput,
                SCOPE_CHANGES,
                h.get_recent_changes,
            ),
            ToolSpec(
                "get_configuration_diff",
                "Key-level diff between two checkout config versions.",
                GetConfigurationDiffInput,
                SCOPE_CHANGES,
                h.get_configuration_diff,
            ),
            ToolSpec(
                "run_allowlisted_diagnostic",
                "service_readiness: /ready of each service. "
                "tcp_connect_configured_endpoints: TCP connect to each URL in checkout's active config.",
                RunDiagnosticInput,
                SCOPE_DIAGNOSTICS,
                h.run_allowlisted_diagnostic,
                timeout_s=12.0,
            ),
        ]
    )
