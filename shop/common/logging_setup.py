"""Structured JSON logging with request/trace correlation and redaction.

Log calls attach structured fields via ``extra={"fields": {...}}``::

    log.error("payment call failed", extra={"fields": {"dependency": "payment"}})

Every line carries: ts, level, service, logger, msg, request_id, trace_id,
span_id and the redacted ``fields``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from shop.common.context import request_id_var, synthetic_var
from shop.common.redaction import redact, redact_text

MAX_MESSAGE_CHARS = 2_000


def _current_trace_ids() -> tuple[str | None, str | None]:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - otel always present in services
        return None, None
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _current_trace_ids()
        msg = redact_text(record.getMessage())[:MAX_MESSAGE_CHARS]
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": msg,
            "request_id": request_id_var.get(),
            "trace_id": trace_id,
            "span_id": span_id,
        }
        if synthetic_var.get():
            payload["synthetic"] = True
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            payload["fields"] = redact(fields)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))[:MAX_MESSAGE_CHARS]
        return json.dumps(payload, default=str)


def configure_logging(service: str, level: str = "INFO", loki_push_url: str | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    formatter = JsonFormatter(service)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    root.addHandler(stdout)

    if loki_push_url:
        from shop.common.loki_handler import LokiHandler

        loki = LokiHandler(loki_push_url, labels={"service": service, "app": "shop"})
        loki.setFormatter(formatter)
        root.addHandler(loki)

    # Uvicorn's access log duplicates our own request log line.
    logging.getLogger("uvicorn.access").disabled = True
