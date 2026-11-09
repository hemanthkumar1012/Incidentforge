"""Ports the remediation services use to reach the shop and the sandbox.

Each port is backed by a different database role or network path (see
docs/access-boundary.md): reading config uses ``forge_reader``, writing a
rollback uses ``forge_remediator``, verification calls the public checkout API,
and validation talks only to the sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from forge.validation.runner import SandboxPort

__all__ = ["ConfigReader", "ConfigWriter", "RecoveryVerifier", "SandboxPort", "VerificationReport"]


class ConfigReader(Protocol):
    def active(self, service: str) -> dict[str, Any] | None: ...
    def version(self, service: str, version: int) -> dict[str, Any] | None: ...
    def versions(self, service: str, limit: int = 50) -> list[dict[str, Any]]: ...


class ConfigWriter(Protocol):
    def rollback(self, service: str, to_version: int, *, expected_active_version: int, author: str, reason: str) -> int:
        """Roll forward to a copy of ``to_version``; returns the new version.

        Raises ``shop.config_admin.ConfigWriteError`` if the active version is no
        longer ``expected_active_version``.
        """
        ...


@dataclass
class VerificationReport:
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)


class RecoveryVerifier(Protocol):
    def verify(self) -> VerificationReport: ...
