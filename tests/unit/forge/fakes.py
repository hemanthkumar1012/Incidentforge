"""In-memory telemetry ports for forge unit tests.

``FakeTelemetry.config_endpoint_fault()`` models the *shape* of a caller-side
misconfiguration (connect errors, dependency healthy, recent config change),
built from generic signals, not from lab files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from forge.investigation.tool_catalog import build_registry
from forge.telemetry.ports import TelemetryUnavailable

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
BASE = {"payment_url": "http://payment:8002", "inventory_url": "http://inventory:8001"}


def series(labels: dict[str, str], value: float) -> dict[str, Any]:
    return {"labels": labels, "values": [[1, str(value)], [2, str(value)]]}


class FakeTelemetry:
    def __init__(self) -> None:
        self.metric_responses: dict[str, list[dict[str, Any]]] = {}
        self.log_lines: list[dict[str, Any]] = []
        self.versions = {
            1: {
                "version": 1,
                "payload": dict(BASE),
                "author": "bootstrap",
                "created_at": "2026-11-08T10:00:00Z",
            }
        }
        self.active_version = 1
        self.events: list[dict[str, Any]] = []
        self.ready = {"checkout": True, "inventory": True, "payment": True}
        self.listening = {("payment", 8002), ("inventory", 8001)}
        self.unavailable: set[str] = set()
        self.queries: list[str] = []

    # --- scenario shapes --------------------------------------------------
    @classmethod
    def healthy(cls) -> FakeTelemetry:
        t = cls()
        t.metric_responses["dependency_requests_total"] = [
            series({"dependency": "payment", "outcome": "success"}, 120),
            series({"dependency": "inventory", "outcome": "success"}, 240),
        ]
        return t

    @classmethod
    def config_endpoint_fault(cls) -> FakeTelemetry:
        t = cls.healthy()
        t.versions[2] = {
            "version": 2,
            "payload": {**BASE, "payment_url": "http://payment:8020"},
            "author": "release-pipeline",
            "created_at": "2026-11-08T11:50:00Z",
        }
        t.active_version = 2
        t.events.append(
            {
                "id": 2,
                "occurred_at": "2026-11-08T11:50:00Z",
                "service": "checkout",
                "kind": "config_change",
                "summary": "checkout config update",
                "actor": "release-pipeline",
                "from_version": 1,
                "to_version": 2,
            }
        )
        t.metric_responses["checkout_orders_total"] = [series({"reason": "payment_unavailable"}, 40)]
        t.metric_responses["dependency_requests_total"] = [
            series({"dependency": "payment", "outcome": "connect_error"}, 80),
            series({"dependency": "inventory", "outcome": "success"}, 160),
        ]
        return t

    # --- ports ------------------------------------------------------------
    def _check(self, backend: str) -> None:
        if backend in self.unavailable:
            raise TelemetryUnavailable(f"{backend} unreachable")

    def query_range(self, query, start, end, step_s):
        self._check("metrics")
        self.queries.append(query)
        for key, value in self.metric_responses.items():
            if key in query:
                return value
        return []

    def query(self, logql, start, end, limit):
        self._check("logs")
        return self.log_lines[:limit]

    def find(self, service, *, errors_only, start, end, limit, min_duration_ms):
        self._check("traces")
        return []

    def get(self, trace_id):
        self._check("traces")
        return None

    def recent(self, service, since, limit):
        self._check("changes")
        return [e for e in self.events if service in (None, e["service"])][:limit]

    def version(self, service, version):
        self._check("changes")
        return self.versions.get(version)

    def active(self, service):
        self._check("changes")
        return self.versions[self.active_version]

    def readiness(self, service):
        return {"ready": self.ready[service], "status_code": 200 if self.ready[service] else 503}

    def tcp_connect(self, host, port):
        ok = (host, port) in self.listening
        return {"reachable": ok, "error": None if ok else "connection refused"}

    def registry(self):
        return build_registry(self, self, self, self, self, clock=lambda: NOW)
