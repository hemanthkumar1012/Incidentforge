"""Async read path for runtime configuration with a short TTL cache.

Fail-closed: if the active payload does not validate, the load raises
``ConfigUnavailable`` and checkout returns 503 instead of guessing. The error
is logged and counted so it is visible as evidence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shop.common.config_schema import CheckoutConfig
from shop.common.telemetry import CONFIG_LOAD_ERRORS, CONFIG_VERSION
from shop.models import ConfigVersion

log = logging.getLogger("shop.config")


class ConfigUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedConfig:
    version: int
    config: CheckoutConfig


class CheckoutConfigStore:
    def __init__(self, sessionmaker: async_sessionmaker, *, observer: str, ttl_s: float = 3.0) -> None:
        self._sessionmaker = sessionmaker
        self._observer = observer
        self._ttl_s = ttl_s
        self._cached: LoadedConfig | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> LoadedConfig:
        now = time.monotonic()
        if self._cached is not None and now - self._loaded_at < self._ttl_s:
            return self._cached
        async with self._lock:
            if self._cached is not None and time.monotonic() - self._loaded_at < self._ttl_s:
                return self._cached
            loaded = await self._load()
            if self._cached is None or self._cached.version != loaded.version:
                log.info(
                    "runtime config loaded",
                    extra={"fields": {"config_service": "checkout", "version": loaded.version}},
                )
            self._cached = loaded
            self._loaded_at = time.monotonic()
            CONFIG_VERSION.labels(self._observer, "checkout").set(loaded.version)
            return loaded

    async def _load(self) -> LoadedConfig:
        async with self._sessionmaker() as session:
            row = (
                await session.scalars(
                    select(ConfigVersion).where(ConfigVersion.service == "checkout", ConfigVersion.active.is_(True))
                )
            ).one_or_none()
        if row is None:
            CONFIG_LOAD_ERRORS.labels(self._observer, "checkout").inc()
            raise ConfigUnavailable("no active checkout configuration")
        try:
            cfg = CheckoutConfig.model_validate(row.payload)
        except ValidationError as exc:
            CONFIG_LOAD_ERRORS.labels(self._observer, "checkout").inc()
            log.error(
                "runtime config failed validation",
                extra={
                    "fields": {
                        "config_service": "checkout",
                        "version": row.version,
                        "errors": [{"loc": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()],
                    }
                },
            )
            raise ConfigUnavailable(f"checkout config version {row.version} is invalid") from exc
        return LoadedConfig(version=row.version, config=cfg)
