"""Executing an approved action and verifying recovery.

Concurrency and idempotency:

* ``request`` returns the existing job if one exists for the proposal (unique
  constraint), so double-clicks and retries never create a second execution.
* The approval is consumed with a conditional UPDATE (``status='approved'``).
  Of two concurrent requests only one consumes it; the loser re-reads and returns
  the winner's job.
* The config write uses ``expected_active_version``: if production moved after
  approval, the write is refused and the job ends ``refused`` with a reason;
  a new validation and approval are required.

Unapproved writes never happen: there is no automatic rollback after a failed
verification. The rollback procedure is shown to the operator and goes through
the same propose → validate → approve path.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from forge.db.models import Approval, Incident, Proposal, RecoveryJob
from forge.domain.policy import execution_refusals
from forge.domain.states import INCIDENT, PROPOSAL, RECOVERY
from forge.jobs.queue import enqueue
from forge.services.approvals import binding_for, expire_if_due, snapshot
from forge.services.common import Conflict, PreconditionFailed, audit, get_or_404, move, new_id, utcnow
from forge.services.ports import ConfigReader, ConfigWriter, RecoveryVerifier
from forge.services.proposals import require_validated
from shop.config_admin import ConfigWriteError


def _current_refusals(
    session: Session, proposal: Proposal, approval: Approval, reader: ConfigReader, *, consumed: bool = False
) -> list[str]:
    """Policy check against live production state.

    ``consumed=True`` is used at execution time: the approval was legitimately
    consumed by this job, so only digest, expiry and config version are checked.
    """
    run = require_validated(session, proposal)
    active = reader.active(proposal.target)
    view = replace(snapshot(approval), status="approved") if consumed else snapshot(approval)
    return execution_refusals(
        view,
        current_binding_digest=binding_for(proposal, run.id).digest(),
        expected_active_version=proposal.expected_active_version,
        current_active_version=active["version"] if active else None,
        now=utcnow(),
    )


def request(session: Session, proposal_id: str, *, actor: str, reader: ConfigReader) -> tuple[RecoveryJob, bool]:
    """Returns (job, created). Idempotent per proposal."""
    existing = session.scalars(select(RecoveryJob).where(RecoveryJob.proposal_id == proposal_id)).first()
    if existing is not None:
        return existing, False
    proposal = get_or_404(session, Proposal, proposal_id)
    approval = session.scalars(
        select(Approval).where(Approval.proposal_id == proposal_id, Approval.status == "approved")
    ).first()
    if approval is None:
        raise PreconditionFailed("no approved approval for this proposal")
    if expire_if_due(session, approval):
        raise PreconditionFailed("approval expired before execution; request a new approval")
    refusals = _current_refusals(session, proposal, approval, reader)
    if refusals:
        # Refuse without mutating: this request's transaction is rolled back by the
        # caller. The approval stays unusable while state differs (every request
        # re-checks) and is retired by re-validation or expiry.
        raise PreconditionFailed("; ".join(refusals), details={"reasons": refusals})

    consumed = session.execute(
        update(Approval).where(Approval.id == approval.id, Approval.status == "approved").values(status="consumed")
    ).rowcount
    if not consumed:
        # A concurrent request consumed it first; return that request's job.
        winner = session.scalars(select(RecoveryJob).where(RecoveryJob.proposal_id == proposal_id)).first()
        if winner is None:
            raise Conflict("approval was consumed concurrently; retry")
        return winner, False
    job = RecoveryJob(
        id=new_id("rec"),
        proposal_id=proposal.id,
        approval_id=approval.id,
        status="requested",
        requested_by=actor,
        result={},
    )
    session.add(job)
    incident = session.get(Incident, proposal.incident_id)
    if incident is not None and incident.status == "diagnosed":
        move(INCIDENT, incident, "remediating")
    session.flush()
    enqueue(session, "recovery", job.id, max_attempts=1)  # never auto-retry a production write
    audit(
        session,
        actor,
        "recovery.requested",
        "recovery_job",
        job.id,
        incident_id=proposal.incident_id,
        approval_id=approval.id,
        approved_by=approval.decided_by,
    )
    return job, True


def execute(
    sessions: sessionmaker[Session],
    job_id: str,
    reader: ConfigReader,
    writer: ConfigWriter,
    verifier: RecoveryVerifier,
) -> str:
    with sessions.begin() as s:
        job = s.get(RecoveryJob, job_id, with_for_update=True)
        if job is None or job.status != "requested":
            return job.status if job else "missing"
        proposal = get_or_404(s, Proposal, job.proposal_id)
        approval = get_or_404(s, Approval, job.approval_id)
        move(RECOVERY, job, "executing")
        incident_id = proposal.incident_id
        # Production may have moved between request and execution: re-check.
        refusals = _current_refusals(s, proposal, approval, reader, consumed=True)
        if refusals:
            return _finish(s, job, "refused", incident_id, reasons=refusals)
        target, to_version, expected = (
            proposal.target,
            proposal.parameters["to_version"],
            proposal.expected_active_version,
        )
        author = f"forge/{job.requested_by} approved-by {approval.decided_by}"

    try:
        new_version = writer.rollback(
            target,
            to_version,
            expected_active_version=expected,
            author=author,
            reason=f"approved recovery {job_id}",
        )
    except ConfigWriteError as exc:
        with sessions.begin() as s:
            job = get_or_404(s, RecoveryJob, job_id)
            return _finish(s, job, "refused", incident_id, reasons=[str(exc)])

    with sessions.begin() as s:
        job = get_or_404(s, RecoveryJob, job_id)
        job.config_version_before, job.config_version_after = expected, new_version
        move(RECOVERY, job, "verifying")
        proposal = get_or_404(s, Proposal, job.proposal_id)
        move(PROPOSAL, proposal, "executed")
        audit(
            s,
            "executor",
            "recovery.applied",
            "recovery_job",
            job.id,
            incident_id=incident_id,
            config_version_before=expected,
            config_version_after=new_version,
        )

    report = verifier.verify()
    with sessions.begin() as s:
        job = get_or_404(s, RecoveryJob, job_id)
        job.result = {**job.result, "verification": {"passed": report.passed, "checks": report.checks}}
        return _finish(s, job, "succeeded" if report.passed else "verification_failed", incident_id)


def _finish(session: Session, job: RecoveryJob, status: str, incident_id: str, **details: object) -> str:
    move(RECOVERY, job, status)
    job.finished_at = utcnow()
    if details:
        job.result = {**job.result, **details}
    incident = session.get(Incident, incident_id)
    if incident is not None and incident.status == "remediating":
        move(INCIDENT, incident, "resolved" if status == "succeeded" else "diagnosed")
        if status == "succeeded":
            incident.resolved_at = utcnow()
    audit(session, "executor", f"recovery.{status}", "recovery_job", job.id, incident_id=incident_id, **details)
    return status
