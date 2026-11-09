"""Proposals, validation, approvals and recovery."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from forge.api import serializers as ser
from forge.api.deps import container, db, require
from forge.db.models import Approval, Proposal, RecoveryJob
from forge.domain.policy import Actor, Permission
from forge.services import approvals, proposals, recovery
from forge.services.common import get_or_404
from forge.wiring import Container

router = APIRouter(prefix="/api", tags=["remediation"])


class Decision(BaseModel):
    approve: bool
    note: str = Field(min_length=3, max_length=1000)
    binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$", description="digest of the action you reviewed")


@router.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: str, session: Session = Depends(db), _: Actor = Depends(require(Permission.READ))
) -> dict[str, Any]:
    proposal = get_or_404(session, Proposal, proposal_id)
    run = proposals.latest_validation(session, proposal_id)
    return {**ser.proposal(proposal), "latest_validation": ser.validation(run) if run else None}


@router.post("/proposals/{proposal_id}/validations", status_code=202)
def request_validation(
    proposal_id: str,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.REQUEST_VALIDATION)),
) -> dict[str, Any]:
    return ser.validation(proposals.request_validation(session, proposal_id, actor=actor.username))


@router.post("/proposals/{proposal_id}/approvals", status_code=201)
def request_approval(
    proposal_id: str,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.REQUEST_APPROVAL)),
) -> dict[str, Any]:
    return ser.approval(approvals.request(session, proposal_id, actor=actor.username))


@router.get("/approvals")
def approval_queue(
    session: Session = Depends(db), _: Actor = Depends(require(Permission.READ)), status: str = "pending"
) -> dict[str, Any]:
    rows = session.scalars(
        select(Approval).where(Approval.status == status).order_by(Approval.requested_at.desc()).limit(100)
    ).all()
    props = (
        {p.id: p for p in session.scalars(select(Proposal).where(Proposal.id.in_([a.proposal_id for a in rows])))}
        if rows
        else {}
    )
    return {
        "items": [
            {
                **ser.approval(a),
                "incident_id": props[a.proposal_id].incident_id,
                "expected_effect": props[a.proposal_id].details.get("expected_effect", []),
            }
            for a in rows
        ]
    }


@router.post("/approvals/{approval_id}/decision")
def decide(
    approval_id: str,
    body: Decision,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.DECIDE_APPROVAL)),
) -> dict[str, Any]:
    return ser.approval(
        approvals.decide(
            session,
            approval_id,
            actor=actor,
            approve=body.approve,
            note=body.note,
            expected_digest=body.binding_digest,
        )
    )


@router.post("/proposals/{proposal_id}/recovery")
def request_recovery(
    proposal_id: str,
    response: Response,
    session: Session = Depends(db),
    actor: Actor = Depends(require(Permission.EXECUTE_RECOVERY)),
    c: Container = Depends(container),
) -> dict[str, Any]:
    job, created = recovery.request(session, proposal_id, actor=actor.username, reader=c.config_history)
    response.status_code = 202 if created else 200
    return {**ser.recovery(job), "created": created}


@router.get("/recovery/{job_id}")
def get_recovery(
    job_id: str, session: Session = Depends(db), _: Actor = Depends(require(Permission.READ))
) -> dict[str, Any]:
    return ser.recovery(get_or_404(session, RecoveryJob, job_id))
