"""Incident registration, listing and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from forge.db.models import Incident
from forge.domain.states import INCIDENT
from forge.services.common import audit, get_or_404, move, new_id, utcnow

SortField = Literal["created_at", "severity", "status"]


@dataclass(frozen=True)
class IncidentPage:
    items: list[Incident]
    total: int
    page: int
    page_size: int


def register(
    session: Session, *, actor: str, title: str, severity: str, signal: dict[str, Any], source: str = "manual"
) -> Incident:
    incident = Incident(
        id=new_id("inc"),
        title=title,
        status="open",
        severity=severity,
        source=source,
        signal=signal,
        created_by=actor,
    )
    session.add(incident)
    session.flush()
    audit(
        session,
        actor,
        "incident.registered",
        "incident",
        incident.id,
        incident_id=incident.id,
        severity=severity,
        source=source,
    )
    return incident


def register_detected(session: Session, *, title: str, severity: str, signal: dict[str, Any]) -> Incident | None:
    """Create a detector incident unless one is already open (dedupe via partial unique index)."""
    incident_id = new_id("inc")
    inserted = session.scalar(
        insert(Incident)
        .values(
            id=incident_id,
            title=title,
            status="open",
            severity=severity,
            source="detector",
            signal=signal,
            created_by="detector",
            version=1,
        )
        .on_conflict_do_nothing()
        .returning(Incident.id)
    )
    if inserted is None:
        return None
    audit(
        session,
        "detector",
        "incident.detected",
        "incident",
        incident_id,
        incident_id=incident_id,
        signal=signal,
    )
    return session.get(Incident, incident_id)


def list_incidents(
    session: Session,
    *,
    status: str | None = None,
    query: str | None = None,
    sort: SortField = "created_at",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> IncidentPage:
    stmt = select(Incident)
    if status:
        stmt = stmt.where(Incident.status == status)
    if query:
        stmt = stmt.where(Incident.title.ilike(f"%{query}%"))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = getattr(Incident, sort)
    stmt = stmt.order_by(column.desc() if descending else column.asc(), Incident.id)
    items = list(session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return IncidentPage(items, total, page, page_size)


def transition(session: Session, incident_id: str, target: str, *, actor: str, reason: str = "") -> Incident:
    incident = get_or_404(session, Incident, incident_id)
    previous = move(INCIDENT, incident, target)
    if target == "resolved":
        incident.resolved_at = utcnow()
    audit(
        session,
        actor,
        "incident.status_changed",
        "incident",
        incident.id,
        incident_id=incident.id,
        previous=previous,
        current=target,
        reason=reason,
    )
    return incident
