"""Interfaces between the investigator tools and telemetry backends.

Tools depend on these protocols, not on Prometheus/Loki/Jaeger client code,
so tool behaviour (bounds, shaping, error mapping) is tested with in-memory
fakes and the HTTP adapters are tested separately against real backends.
Adapters raise ``TelemetryUnavailable`` for backend failures; tools turn it
into a structured ``backend_unavailable`` error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class TelemetryUnavailable(RuntimeError):
    pass


class MetricsBackend(Protocol):
    def query_range(self, query: str, start: datetime, end: datetime, step_s: int) -> list[dict[str, Any]]:
        """Series as ``[{"labels": {...}, "values": [[unix_ts, float], ...]}]``."""
        ...


class LogsBackend(Protocol):
    def query(self, logql: str, start: datetime, end: datetime, limit: int) -> list[dict[str, Any]]:
        """Lines as ``[{"ts": iso8601, "labels": {...}, "line": str}]``, newest first."""
        ...


class TracesBackend(Protocol):
    def find(
        self,
        service: str,
        *,
        errors_only: bool,
        start: datetime,
        end: datetime,
        limit: int,
        min_duration_ms: int | None,
    ) -> list[dict[str, Any]]: ...

    def get(self, trace_id: str) -> dict[str, Any] | None: ...


class ChangeHistory(Protocol):
    def recent(self, service: str | None, since: datetime, limit: int) -> list[dict[str, Any]]: ...
    def version(self, service: str, version: int) -> dict[str, Any] | None: ...
    def active(self, service: str) -> dict[str, Any] | None: ...


class Diagnostics(Protocol):
    def readiness(self, service: str) -> dict[str, Any]: ...
    def tcp_connect(self, host: str, port: int) -> dict[str, Any]: ...
