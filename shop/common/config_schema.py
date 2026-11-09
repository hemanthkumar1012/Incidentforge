"""Schema for versioned runtime configuration.

Checkout reads its dependency endpoints and timeouts from the
``config_versions`` table at runtime (with a short cache). This is what makes
configuration faults realistic and investigable: every change produces a new
immutable version plus a ``change_events`` row that the investigator can query.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_service_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")
    if not parts.hostname:
        raise ValueError("URL must include a host")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("URL must not contain query, fragment or credentials")
    _ = parts.port  # raises ValueError for an out-of-range port
    return value.rstrip("/")


class CheckoutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_url: str
    inventory_url: str
    payment_timeout_s: float = Field(default=2.0, gt=0, le=30)
    inventory_timeout_s: float = Field(default=2.0, gt=0, le=30)
    max_items_per_order: int = Field(default=20, ge=1, le=100)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    @field_validator("payment_url", "inventory_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _validate_service_url(v)


CONFIG_SCHEMAS: dict[str, type[BaseModel]] = {"checkout": CheckoutConfig}


def validate_config(service: str, payload: dict[str, Any]) -> BaseModel:
    try:
        schema = CONFIG_SCHEMAS[service]
    except KeyError as exc:
        raise ValueError(f"no config schema registered for service {service!r}") from exc
    return schema.model_validate(payload)


def config_diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Key-level diff between two config payloads (stable ordering)."""
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            changes.append({"key": key, "op": "added", "new": new[key]})
        elif key not in new:
            changes.append({"key": key, "op": "removed", "old": old[key]})
        elif old[key] != new[key]:
            changes.append({"key": key, "op": "changed", "old": old[key], "new": new[key]})
    return changes
