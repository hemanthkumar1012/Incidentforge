"""Incidents, investigations, evidence and the incident timeline."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from forge.api import serializers as ser
from forge.api.deps import container, db, require
from forge.db.models import (
    Approval,
    AuditEvent,
    Evidence,
    Incident,
    Investigation,
    InvestigationStep,
    Proposal,
    RecoveryJob,
    ValidationRun,
)
from forge.domain.policy import Actor, Permission
from forge.services import incidents, investigations
from forge.services.common import get_or_404
from forge.wiring import Container

router = APIRouter(prefix="/api", tags=["incidents"])


class RegisterIncident(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    severity: Literal["sev1", "sev2", "sev3"] = "sev2"
    description: str = Field(default="", max_length=2000)


class StartInvestigation(BaseModel):
    mode: Literal["llm", "runbook", "llm_summary"] | None = None


class CloseIncident(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/incidents")
def list_incidents(
    session: Session = Depends(db),
    _: Actor = Depends(require(Permission.READ)),
    status: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    sort: Literal["created_at", "severity", "status"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    result = incidents.list_incidents(
        session, status=status, query=q, sort=sort, descending=order == "desc", page=page, page_size=page_size
    )
    return {
        "items": [ser.incident(i) for i in result.items],
        "total": result.total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/incidents", status_code=201)
def register_incident(
    body: RegisterIncident,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.REGISTER_INCIDENT)),
) -> dict[str, Any]:
    incident = incidents.register(
        session,
        actor=actor.username,
        title=body.title,
        severity=body.severity,
        signal={"description": body.description} if body.description else {},
    )
    return ser.incident(incident)


@router.get("/incidents/{incident_id}")
def incident_workspace(
    incident_id: str, session: Session = Depends(db), _: Actor = Depends(require(Permission.READ))
) -> dict[str, Any]:
    """Everything the incident workspace needs in one consistent snapshot."""
    incident = get_or_404(session, Incident, incident_id)
    invs = session.scalars(
        select(Investigation).where(Investigation.incident_id == incident_id).order_by(Investigation.created_at.desc())
    ).all()
    props = session.scalars(
        select(Proposal).where(Proposal.incident_id == incident_id).order_by(Proposal.created_at.desc())
    ).all()
    prop_ids = [p.id for p in props]
    vals = (
        session.scalars(
            select(ValidationRun)
            .where(ValidationRun.proposal_id.in_(prop_ids))
            .order_by(ValidationRun.created_at.desc())
        ).all()
        if prop_ids
        else []
    )
    aprs = (
        session.scalars(
            select(Approval).where(Approval.proposal_id.in_(prop_ids)).order_by(Approval.requested_at.desc())
        ).all()
        if prop_ids
        else []
    )
    recs = session.scalars(select(RecoveryJob).where(RecoveryJob.proposal_id.in_(prop_ids))).all() if prop_ids else []
    return {
        "incident": ser.incident(incident),
        "investigations": [ser.investigation(v) for v in invs],
        "proposals": [ser.proposal(p) for p in props],
        "validations": [ser.validation(v) for v in vals],
        "approvals": [ser.approval(a) for a in aprs],
        "recoveries": [ser.recovery(r) for r in recs],
    }


@router.post("/incidents/{incident_id}/close")
def close_incident(
    incident_id: str,
    body: CloseIncident,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.CLOSE_INCIDENT)),
) -> dict[str, Any]:
    return ser.incident(incidents.transition(session, incident_id, "closed", actor=actor.username, reason=body.reason))


@router.post("/incidents/{incident_id}/investigations", status_code=202)
def start_investigation(
    incident_id: str,
    body: StartInvestigation,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.RUN_INVESTIGATION)),
    c: Container = Depends(container),
) -> dict[str, Any]:
    mode = body.mode or c.settings.default_mode
    provider, model = c.provider_info(mode)  # type: ignore[arg-type]
    inv = investigations.start(
        session,
        incident_id,
        mode=mode,
        actor=actor.username,  # type: ignore[arg-type]
        provider=provider,
        model=model,
    )
    return ser.investigation(inv)


@router.get("/investigations/{investigation_id}")
def get_investigation(
    investigation_id: str, session: Session = Depends(db), _: Actor = Depends(require(Permission.READ))
) -> dict[str, Any]:
    inv = get_or_404(session, Investigation, investigation_id)
    steps = session.scalars(
        select(InvestigationStep).where(InvestigationStep.investigation_id == inv.id).order_by(InvestigationStep.seq)
    ).all()
    ev = session.scalars(select(Evidence).where(Evidence.investigation_id == inv.id).order_by(Evidence.id)).all()
    return {
        **ser.investigation(inv),
        "steps": [ser.step(s) for s in steps],
        "evidence": [ser.evidence(e) for e in ev],
    }


@router.get("/incidents/{incident_id}/timeline")
def incident_timeline(
    incident_id: str, session: Session = Depends(db), _: Actor = Depends(require(Permission.READ))
) -> dict[str, Any]:
    get_or_404(session, Incident, incident_id)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.incident_id == incident_id).order_by(AuditEvent.occurred_at, AuditEvent.id)
    ).all()
    return {"items": [ser.audit_event(e) for e in events]}
