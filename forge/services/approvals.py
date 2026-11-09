"""Exact-action approvals.

An approval request snapshots the binding (action, target, params, expected
config version, validation run) and its digest. Deciding locks the row
(``FOR UPDATE``) so two approvers cannot race, applies the pure policy, and
expires requests lazily when they are touched after ``expires_at``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from forge.db.models import Approval, Proposal
from forge.domain.binding import ActionBinding
from forge.domain.policy import Actor, ApprovalSnapshot, approval_decision_refusals
from forge.domain.states import APPROVAL
from forge.services.common import Conflict, Forbidden, audit, get_or_404, move, new_id, utcnow
from forge.services.proposals import require_validated

APPROVAL_TTL = timedelta(minutes=15)


def binding_for(proposal: Proposal, validation_run_id: str) -> ActionBinding:
    return ActionBinding(
        proposal.action_type,
        proposal.target,
        dict(proposal.parameters),
        proposal.expected_active_version,
        validation_run_id,
    )


def snapshot(approval: Approval) -> ApprovalSnapshot:
    return ApprovalSnapshot(approval.status, approval.requested_by, approval.binding_digest, approval.expires_at)


def request(session: Session, proposal_id: str, *, actor: str) -> Approval:
    proposal = get_or_404(session, Proposal, proposal_id)
    run = require_validated(session, proposal)
    open_ = session.scalars(
        select(Approval).where(Approval.proposal_id == proposal.id, Approval.status.in_(("pending", "approved")))
    ).first()
    if open_ is not None:
        raise Conflict("an approval for this proposal is already open", details={"approval_id": open_.id})
    binding = binding_for(proposal, run.id)
    approval = Approval(
        id=new_id("apr"),
        proposal_id=proposal.id,
        validation_run_id=run.id,
        binding=asdict(binding),
        binding_digest=binding.digest(),
        status="pending",
        requested_by=actor,
        expires_at=utcnow() + APPROVAL_TTL,
    )
    session.add(approval)
    session.flush()
    audit(
        session,
        actor,
        "approval.requested",
        "approval",
        approval.id,
        incident_id=proposal.incident_id,
        binding_digest=approval.binding_digest,
        binding=approval.binding,
    )
    return approval


def expire_if_due(session: Session, approval: Approval) -> bool:
    if approval.status in ("pending", "approved") and utcnow() >= approval.expires_at:
        move(APPROVAL, approval, "expired")
        audit(session, "system", "approval.expired", "approval", approval.id)
        return True
    return False


def decide(
    session: Session, approval_id: str, *, actor: Actor, approve: bool, note: str, expected_digest: str
) -> Approval:
    """Approve or reject. ``expected_digest`` is the digest the approver was shown;
    if the request changed underneath them, the decision is refused."""
    approval = session.get(Approval, approval_id, with_for_update=True)
    if approval is None:
        raise Conflict(f"approval {approval_id} not found")
    if expire_if_due(session, approval):
        raise Conflict("approval request has expired; request a new one")
    if expected_digest != approval.binding_digest:
        raise Conflict("the action shown to you differs from the one awaiting approval; reload")
    refusals = approval_decision_refusals(actor, snapshot(approval), utcnow())
    if refusals:
        raise Forbidden("; ".join(refusals), details={"reasons": refusals})
    move(APPROVAL, approval, "approved" if approve else "rejected")
    approval.decided_by, approval.decided_at, approval.note = actor.username, utcnow(), note
    proposal = session.get(Proposal, approval.proposal_id)
    audit(
        session,
        actor.username,
        "approval.approved" if approve else "approval.rejected",
        "approval",
        approval.id,
        incident_id=proposal.incident_id if proposal else None,
        note=note,
        binding_digest=approval.binding_digest,
    )
    return approval
