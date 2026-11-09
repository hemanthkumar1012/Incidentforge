"""Environment-driven settings. Secrets come only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value not in ("", None) else None


def _require(name: str) -> str:
    value = _env(name)
    if value is None:
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class ServiceSettings:
    service_name: str
    database_url: str | None
    log_level: str
    otlp_traces_endpoint: str | None
    loki_push_url: str | None
    lab_admin_token: str | None
    config_cache_ttl_s: float

    @classmethod
    def from_env(cls, service_name: str) -> ServiceSettings:
        return cls(
            service_name=service_name,
            database_url=_env("SHOP_DATABASE_URL"),
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
            otlp_traces_endpoint=_env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
            loki_push_url=_env("LOKI_PUSH_URL"),
            lab_admin_token=_env("LAB_ADMIN_TOKEN"),
            config_cache_ttl_s=float(_env("CONFIG_CACHE_TTL_S", "3") or "3"),
        )
