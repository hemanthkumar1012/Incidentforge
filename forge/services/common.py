"""Shared service-layer primitives: errors, IDs, clock, audit, status changes.

Transaction convention: each public service function receives a ``Session``
whose transaction the *caller* owns (API request or worker job). Services
flush but never commit, so one request = one transaction, and the audit event
for a change commits atomically with the change itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from forge.db.models import AuditEvent
from forge.domain.states import StateMachine


class ServiceError(Exception):
    """Base for errors the API maps to HTTP responses."""

    status_code = 400
    code = "bad_request"

    def __init__(
        self, message: str, *, details: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


class NotFound(ServiceError):
    status_code, code = 404, "not_found"


class Forbidden(ServiceError):
    status_code, code = 403, "forbidden"


class Conflict(ServiceError):
    status_code, code = 409, "conflict"


class PreconditionFailed(ServiceError):
    status_code, code = 412, "precondition_failed"


class TooManyRequests(ServiceError):
    status_code, code = 429, "too_many_requests"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def audit(
    session: Session,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    *,
    incident_id: str | None = None,
    **details: Any,
) -> None:
    session.add(
        AuditEvent(
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            incident_id=incident_id,
            details=details,
        )
    )


class _HasStatus(Protocol):
    status: str


def move(machine: StateMachine, row: _HasStatus, target: str) -> str:
    """Apply a state transition to ``row`` or raise ``Conflict`` with the rule that failed."""
    if not machine.can(row.status, target):
        raise Conflict(
            f"{machine.name} cannot move from {row.status!r} to {target!r}",
            details={"current": row.status, "target": target},
        )
    previous = row.status
    row.status = target
    return previous


def get_or_404(session: Session, model: type, key: str) -> Any:
    row = session.get(model, key)
    if row is None:
        raise NotFound(f"{model.__tablename__} {key} not found")
    return row
