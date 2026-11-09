"""HTTP adapters for Prometheus, Loki and Jaeger (v2 query API).

Shared policy: one ``httpx.Client`` per adapter with a hard timeout, responses
capped at ``MAX_RESPONSE_BYTES``, and every transport/HTTP failure mapped to
``TelemetryUnavailable`` with a message that names the backend. No retries here:
the investigator decides whether a failed query is worth repeating, and the
toolkit reports the error as evidence.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from forge.telemetry.ports import TelemetryUnavailable

MAX_RESPONSE_BYTES = 2_000_000


def _get_json(client: httpx.Client, backend: str, url: str, params: dict[str, Any]) -> Any:
    try:
        resp = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise TelemetryUnavailable(f"{backend} unreachable: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise TelemetryUnavailable(f"{backend} returned {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) > MAX_RESPONSE_BYTES:
        raise TelemetryUnavailable(f"{backend} response exceeded {MAX_RESPONSE_BYTES} bytes")
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise TelemetryUnavailable(f"{backend} returned non-JSON") from exc


class PrometheusBackend:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def query_range(self, query: str, start: datetime, end: datetime, step_s: int) -> list[dict[str, Any]]:
        data = _get_json(
            self._client,
            "prometheus",
            f"{self._base}/api/v1/query_range",
            {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_s,
                "timeout": "4s",
            },
        )
        if data.get("status") != "success":
            raise TelemetryUnavailable(f"prometheus query failed: {data.get('error', 'unknown error')}")
        return [{"labels": r.get("metric", {}), "values": r.get("values", [])} for r in data["data"]["result"]]


class LokiBackend:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def query(self, logql: str, start: datetime, end: datetime, limit: int) -> list[dict[str, Any]]:
        data = _get_json(
            self._client,
            "loki",
            f"{self._base}/loki/api/v1/query_range",
            {
                "query": logql,
                "start": int(start.timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": limit,
                "direction": "backward",
            },
        )
        lines = [
            {"ts": ts, "labels": stream.get("stream", {}), "line": line}
            for stream in data.get("data", {}).get("result", [])
            for ts, line in stream.get("values", [])
        ]
        lines.sort(key=lambda e: e["ts"], reverse=True)
        return lines[:limit]


def _span_summary(span: dict[str, Any], processes: dict[str, Any]) -> dict[str, Any]:
    tags = {t["key"]: t.get("value") for t in span.get("tags", [])}
    service = processes.get(span.get("processID", ""), {}).get("serviceName")
    return {
        "span_id": span.get("spanID"),
        "service": service,
        "operation": span.get("operationName"),
        "duration_ms": round(span.get("duration", 0) / 1000, 2),
        "error": tags.get("error") is True or tags.get("otel.status_code") == "ERROR",
        "attributes": tags,
    }


class JaegerBackend:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def find(
        self,
        service: str,
        *,
        errors_only: bool,
        start: datetime,
        end: datetime,
        limit: int,
        min_duration_ms: int | None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "service": service,
            "limit": limit,
            "start": int(start.timestamp() * 1e6),
            "end": int(end.timestamp() * 1e6),
        }
        if errors_only:
            params["tags"] = json.dumps({"error": "true"})
        if min_duration_ms:
            params["minDuration"] = f"{min_duration_ms}ms"
        data = _get_json(self._client, "jaeger", f"{self._base}/api/traces", params)
        out = []
        for trace in (data.get("data") or [])[:limit]:
            spans = trace.get("spans", [])
            processes = trace.get("processes", {})
            root = min(spans, key=lambda s: s.get("startTime", 0), default={})
            out.append(
                {
                    "trace_id": trace.get("traceID"),
                    "root_operation": root.get("operationName"),
                    "duration_ms": round(root.get("duration", 0) / 1000, 2),
                    "span_count": len(spans),
                    "error_spans": sum(1 for s in spans if _span_summary(s, processes)["error"]),
                }
            )
        return out

    def get(self, trace_id: str) -> dict[str, Any] | None:
        try:
            data = _get_json(self._client, "jaeger", f"{self._base}/api/traces/{trace_id}", {})
        except TelemetryUnavailable as exc:
            if "404" in str(exc):
                return None
            raise
        traces = data.get("data") or []
        if not traces:
            return None
        trace = traces[0]
        processes = trace.get("processes", {})
        return {"spans": [_span_summary(s, processes) for s in trace.get("spans", [])]}
