"""Per-request context propagated through logs and outbound calls."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
synthetic_var: ContextVar[bool] = ContextVar("synthetic", default=False)

REQUEST_ID_HEADER = "X-Request-ID"
SYNTHETIC_HEADER = "X-Synthetic"

# Accept only conservative caller-supplied IDs; otherwise mint a new one. This
# stops log injection through the request-id header.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


def accept_request_id(candidate: str | None) -> str:
    if candidate and _VALID_REQUEST_ID.match(candidate):
        return candidate
    return new_request_id()


def parse_synthetic(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}
