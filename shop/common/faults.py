"""In-process fault hooks used by the Incident Lab (System B).

Services expose these hooks only through admin endpoints protected by
``LAB_ADMIN_TOKEN``. The investigator never receives that token, and these
endpoints are not part of any investigator tool. When the token is unset the
admin endpoints are disabled entirely.

Randomness is seeded so that an injected error rate is reproducible across runs.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass

from pydantic import BaseModel, Field


class FaultConfig(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=30_000)
    latency_jitter_ms: int = Field(default=0, ge=0, le=10_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_status: int = Field(default=503, ge=500, le=599)
    seed: int = 1234

    @property
    def active(self) -> bool:
        return self.latency_ms > 0 or self.latency_jitter_ms > 0 or self.error_rate > 0


@dataclass(frozen=True)
class FaultDecision:
    delay_s: float
    error_status: int | None


class FaultInjector:
    """Thread-safe holder for the current fault configuration."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config = FaultConfig()
        # Seeded PRNG on purpose: injected faults must be reproducible, not secure.
        self._rng = random.Random(self._config.seed)  # noqa: S311

    def set(self, config: FaultConfig) -> None:
        with self._lock:
            self._config = config
            self._rng = random.Random(config.seed)  # noqa: S311

    def clear(self) -> None:
        self.set(FaultConfig())

    @property
    def config(self) -> FaultConfig:
        with self._lock:
            return self._config

    def decide(self) -> FaultDecision:
        with self._lock:
            cfg = self._config
            delay_ms = cfg.latency_ms
            if cfg.latency_jitter_ms:
                delay_ms += self._rng.randint(0, cfg.latency_jitter_ms)
            error = cfg.error_status if self._rng.random() < cfg.error_rate else None
        return FaultDecision(delay_s=delay_ms / 1000.0, error_status=error)
