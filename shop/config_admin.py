"""Write path for versioned runtime configuration (sync, used by CLIs).

Used by: the seed command (baseline), the Incident Lab (fault injection and
reset), and later the remediation executor (rollback). Every write:

1. takes a per-service transaction-scoped advisory lock (serialises writers),
2. deactivates the current version and inserts version N+1 as active,
3. appends a ``change_events`` row describing the change.

All three happen in one transaction, so readers never observe a service with
zero or two active versions.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from shop.common.config_schema import validate_config
from shop.models import ChangeEvent, ConfigVersion


class ConfigWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigWriteResult:
    service: str
    from_version: int | None
    to_version: int
    change_event_id: int


def _lock(session: Session, service: str) -> None:
    key = zlib.crc32(f"config:{service}".encode())
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def get_active(session: Session, service: str) -> ConfigVersion | None:
    return session.scalars(
        select(ConfigVersion).where(ConfigVersion.service == service, ConfigVersion.active.is_(True))
    ).one_or_none()


def get_version(session: Session, service: str, version: int) -> ConfigVersion | None:
    return session.scalars(
        select(ConfigVersion).where(ConfigVersion.service == service, ConfigVersion.version == version)
    ).one_or_none()


def apply_config(
    session: Session,
    service: str,
    payload: dict[str, Any],
    *,
    author: str,
    reason: str,
    summary: str,
    validate: bool = True,
    expected_active_version: int | None = None,
    details: dict[str, Any] | None = None,
) -> ConfigWriteResult:
    """Create and activate a new config version. Caller commits.

    ``expected_active_version`` gives optimistic concurrency: if the active
    version moved since the caller looked, the write is refused. Remediation
    (Milestone 3) relies on this to reject stale approvals.

    ``validate=False`` exists only for the Incident Lab's invalid-config scenario.
    """
    if validate:
        validate_config(service, payload)
    _lock(session, service)
    current = get_active(session, service)
    current_version = current.version if current else None
    if expected_active_version is not None and current_version != expected_active_version:
        raise ConfigWriteError(f"active version for {service} is {current_version}, expected {expected_active_version}")
    max_version = session.scalar(select(func.max(ConfigVersion.version)).where(ConfigVersion.service == service))
    new_version = (max_version or 0) + 1
    if current is not None:
        session.execute(update(ConfigVersion).where(ConfigVersion.id == current.id).values(active=False))
        session.flush()
    session.add(
        ConfigVersion(
            service=service,
            version=new_version,
            payload=payload,
            active=True,
            author=author,
            reason=reason,
        )
    )
    event = ChangeEvent(
        service=service,
        kind="config_change",
        summary=summary,
        actor=author,
        from_version=current_version,
        to_version=new_version,
        details=details or {},
    )
    session.add(event)
    session.flush()
    return ConfigWriteResult(service, current_version, new_version, event.id)


def rollback_to_version(
    session: Session,
    service: str,
    target_version: int,
    *,
    author: str,
    reason: str,
    expected_active_version: int | None = None,
) -> ConfigWriteResult:
    """Roll forward to a copy of an older version's payload."""
    target = get_version(session, service, target_version)
    if target is None:
        raise ConfigWriteError(f"{service} has no config version {target_version}")
    return apply_config(
        session,
        service,
        dict(target.payload),
        author=author,
        reason=reason,
        summary=f"{service} config rolled back to the contents of version {target_version}",
        expected_active_version=expected_active_version,
        details={"rollback_of": target_version},
    )
