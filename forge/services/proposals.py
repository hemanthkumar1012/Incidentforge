"""Remediation proposals and their isolated validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from forge.db.models import Approval, Investigation, Proposal, ValidationRun
from forge.domain.states import PROPOSAL
from forge.investigation.schemas import Diagnosis
from forge.jobs.queue import enqueue
from forge.remediation.planner import ConfigVersionView, NoAction, plan_remediation
from forge.services.common import Conflict, PreconditionFailed, audit, get_or_404, move, new_id, utcnow
from forge.services.ports import ConfigReader, SandboxPort
from forge.validation.runner import validate_rollback


@dataclass(frozen=True)
class PlannerInputs:
    reader: ConfigReader


def _history(reader: ConfigReader, service: str) -> tuple[ConfigVersionView, list[ConfigVersionView]]:
    active = reader.active(service)
    if active is None:
        raise PreconditionFailed(f"{service} has no active configuration")
    views = [ConfigVersionView(v["version"], v["payload"], v.get("author", "")) for v in reader.versions(service)]
    return ConfigVersionView(active["version"], active["payload"]), views


def propose_from_diagnosis(
    session: Session, inv: Investigation, diagnosis: Diagnosis, inputs: PlannerInputs
) -> Proposal | None:
    top = diagnosis.top
    if top is None or top.component != "checkout":
        audit(
            session,
            "planner",
            "remediation.none",
            "investigation",
            inv.id,
            incident_id=inv.incident_id,
            reason="no supported target in top hypothesis",
        )
        return None
    active, history = _history(inputs.reader, top.component)
    draft = plan_remediation(diagnosis, active, history)
    if isinstance(draft, NoAction):
        audit(
            session,
            "planner",
            "remediation.none",
            "investigation",
            inv.id,
            incident_id=inv.incident_id,
            reason=draft.reason,
            escalate=draft.escalate,
        )
        return None
    details = {
        k: v
        for k, v in asdict(draft).items()
        if k not in {"action_type", "target", "parameters", "expected_active_version"}
    }
    proposal = Proposal(
        id=new_id("prop"),
        incident_id=inv.incident_id,
        investigation_id=inv.id,
        action_type=draft.action_type,
        target=draft.target,
        parameters=draft.parameters,
        expected_active_version=draft.expected_active_version,
        details=details,
        status="proposed",
        created_by="planner",
    )
    session.add(proposal)
    session.flush()
    audit(
        session,
        "planner",
        "proposal.created",
        "proposal",
        proposal.id,
        incident_id=inv.incident_id,
        action_type=draft.action_type,
        target=draft.target,
        parameters=draft.parameters,
        expected_active_version=draft.expected_active_version,
    )
    return proposal


def request_validation(session: Session, proposal_id: str, *, actor: str) -> ValidationRun:
    proposal = get_or_404(session, Proposal, proposal_id)
    move(PROPOSAL, proposal, "validating")
    _invalidate_open_approvals(session, proposal, actor, "proposal is being re-validated")
    run = ValidationRun(
        id=new_id("val"),
        proposal_id=proposal.id,
        status="queued",
        production_version=proposal.expected_active_version,
        requested_by=actor,
        report={},
    )
    session.add(run)
    session.flush()
    enqueue(session, "validation", run.id)
    audit(
        session,
        actor,
        "validation.requested",
        "proposal",
        proposal.id,
        incident_id=proposal.incident_id,
        validation_run_id=run.id,
    )
    return run


def _invalidate_open_approvals(session: Session, proposal: Proposal, actor: str, reason: str) -> None:
    ids = session.scalars(
        update(Approval)
        .where(Approval.proposal_id == proposal.id, Approval.status.in_(("pending", "approved")))
        .values(status="invalidated", note=reason)
        .returning(Approval.id)
    ).all()
    for approval_id in ids:
        audit(
            session,
            actor,
            "approval.invalidated",
            "approval",
            approval_id,
            incident_id=proposal.incident_id,
            reason=reason,
        )


_VERDICT_TO_PROPOSAL = {
    "passed": "validated",
    "failed": "validation_failed",
    "not_reproducible": "not_reproducible",
    "error": "proposed",
}


def run_validation(
    sessions: sessionmaker[Session],
    run_id: str,
    reader: ConfigReader,
    sandbox: SandboxPort,
    host_map: dict[str, str],
) -> str:
    with sessions.begin() as s:
        run = get_or_404(s, ValidationRun, run_id)
        if run.status != "queued":
            return run.status
        run.status = "running"
        proposal = get_or_404(s, Proposal, run.proposal_id)
        service, to_version, expected = (
            proposal.target,
            proposal.parameters["to_version"],
            proposal.expected_active_version,
        )

    active = reader.active(service)
    target = reader.version(service, to_version)
    if active is None or target is None or active["version"] != expected:
        verdict, report = (
            "error",
            {
                "verdict": "error",
                "steps": [],
                "uncertainty": [
                    f"production config is v{active and active['version']}, proposal expected v{expected}; re-plan"
                ],
            },
        )
    else:
        result = validate_rollback(sandbox, service, active["payload"], target["payload"], host_map)
        verdict, report = (
            result.verdict,
            {"verdict": result.verdict, "steps": result.steps, "uncertainty": result.uncertainty},
        )

    with sessions.begin() as s:
        run = get_or_404(s, ValidationRun, run_id)
        run.status, run.report, run.finished_at = verdict, report, utcnow()
        proposal = get_or_404(s, Proposal, run.proposal_id)
        moved_on = active is not None and active["version"] != expected
        move(PROPOSAL, proposal, "superseded" if moved_on else _VERDICT_TO_PROPOSAL[verdict])
        audit(
            s,
            "validator",
            "validation.finished",
            "proposal",
            proposal.id,
            incident_id=proposal.incident_id,
            validation_run_id=run.id,
            verdict=verdict,
        )
    return verdict


def latest_validation(session: Session, proposal_id: str) -> ValidationRun | None:
    return session.scalars(
        select(ValidationRun).where(ValidationRun.proposal_id == proposal_id).order_by(ValidationRun.created_at.desc())
    ).first()


def require_validated(session: Session, proposal: Proposal) -> ValidationRun:
    run = latest_validation(session, proposal.id)
    if proposal.status != "validated" or run is None or run.status != "passed":
        raise Conflict(
            "proposal must pass isolated validation before approval or execution",
            details={"proposal_status": proposal.status, "validation": run and run.status},
        )
    return run
