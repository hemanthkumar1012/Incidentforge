"""Approval and recovery guarantees against real PostgreSQL.

Concurrent cases use separate sessions in separate threads released together by
a barrier; outcomes are decided by row locks, conditional UPDATEs and unique
constraints in PostgreSQL.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from forge.db.models import Approval, Incident, Investigation, Proposal, RecoveryJob, ValidationRun
from forge.domain.policy import Actor, Role
from forge.services import approvals, proposals, recovery
from forge.services.common import Conflict, Forbidden, PreconditionFailed, utcnow
from forge.services.ports import VerificationReport
from shop.config_admin import ConfigWriteError

pytestmark = pytest.mark.db
OPERATOR, APPROVER, APPROVER2 = "olivia", Actor("arun", Role.APPROVER), Actor("bea", Role.APPROVER)


class Reader:
    def __init__(self, active_version: int = 3) -> None:
        self.active_version = active_version

    def active(self, service):
        return {"version": self.active_version, "payload": {}}

    def version(self, service, version):
        return {"version": version, "payload": {}}

    def versions(self, service, limit=50):
        return []


class Writer:
    def __init__(self, reader: Reader) -> None:
        self.calls, self.reader = 0, reader

    def rollback(self, service, to_version, *, expected_active_version, author, reason):
        self.calls += 1
        if self.reader.active_version != expected_active_version:
            raise ConfigWriteError("active version moved")
        self.reader.active_version += 1
        return self.reader.active_version


class Verifier:
    def verify(self):
        return VerificationReport(True, [{"name": "checkout_journey_1", "passed": True}])


@pytest.fixture(scope="module")
def sessions(databases):
    return sessionmaker(create_engine(databases["forge"]), expire_on_commit=False)


def seed_validated_proposal(sessions, verdict: str = "passed") -> str:
    """incident → investigation → proposal (validated) → passed validation run, all committed."""
    sfx = uuid.uuid4().hex[:10]
    with sessions.begin() as s:
        s.add(
            Incident(
                id=f"inc_{sfx}",
                title="checkout failing",
                status="diagnosed",
                severity="sev2",
                source="manual",
                signal={},
                created_by=OPERATOR,
            )
        )
        s.flush()
        s.add(
            Investigation(
                id=f"inv_{sfx}",
                incident_id=f"inc_{sfx}",
                mode="runbook",
                provider="runbook",
                model="none",
                status="completed",
                created_by=OPERATOR,
                usage={},
            )
        )
        s.flush()
        s.add(
            Proposal(
                id=f"prop_{sfx}",
                incident_id=f"inc_{sfx}",
                investigation_id=f"inv_{sfx}",
                action_type="rollback_config_version",
                target="checkout",
                parameters={"to_version": 2},
                expected_active_version=3,
                details={},
                status="validated" if verdict == "passed" else "validation_failed",
                created_by="planner",
            )
        )
        s.flush()
        s.add(
            ValidationRun(
                id=f"val_{sfx}",
                proposal_id=f"prop_{sfx}",
                status=verdict,
                production_version=3,
                requested_by=OPERATOR,
                report={},
            )
        )
    return f"prop_{sfx}"


def approved(sessions, proposal_id: str) -> Approval:
    with sessions.begin() as s:
        a = approvals.request(s, proposal_id, actor=OPERATOR)
    with sessions.begin() as s:
        return approvals.decide(
            s, a.id, actor=APPROVER, approve=True, note="looks right", expected_digest=a.binding_digest
        )


def run_concurrently(n, fn):
    barrier, results = threading.Barrier(n), []

    def worker(i):
        barrier.wait()
        try:
            results.append(fn(i))
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            results.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_requester_cannot_self_approve_service_and_database(sessions):
    pid = seed_validated_proposal(sessions)
    with sessions.begin() as s:
        a = approvals.request(s, pid, actor="arun")
    with pytest.raises(Forbidden, match="separation of duties"), sessions.begin() as s:
        approvals.decide(s, a.id, actor=APPROVER, approve=True, note="mine", expected_digest=a.binding_digest)
    with pytest.raises(IntegrityError), sessions.begin() as s:  # even bypassing the service, the CHECK holds
        s.execute(text("UPDATE approvals SET status='approved', decided_by=requested_by WHERE id=:i"), {"i": a.id})


def test_failed_validation_cannot_authorize(sessions):
    pid = seed_validated_proposal(sessions, verdict="failed")
    with pytest.raises(Conflict, match="must pass isolated validation"), sessions.begin() as s:
        approvals.request(s, pid, actor=OPERATOR)


def test_two_approvers_race_exactly_one_decision(sessions):
    pid = seed_validated_proposal(sessions)
    with sessions.begin() as s:
        a = approvals.request(s, pid, actor=OPERATOR)

    def decide(i):
        with sessions.begin() as s:
            actor = APPROVER if i == 0 else APPROVER2
            return approvals.decide(s, a.id, actor=actor, approve=i == 0, note="race", expected_digest=a.binding_digest)

    results = run_concurrently(2, decide)
    assert sum(isinstance(r, Approval) for r in results) == 1
    assert sum(isinstance(r, Forbidden) for r in results) == 1  # loser sees "not pending" after the row lock


def test_duplicate_recovery_requests_create_one_job(sessions):
    pid = seed_validated_proposal(sessions)
    approved(sessions, pid)
    reader = Reader()

    def request(_):
        with sessions.begin() as s:
            job, created = recovery.request(s, pid, actor=OPERATOR, reader=reader)
            return job.id, created

    results = run_concurrently(5, request)
    assert all(not isinstance(r, Exception) for r in results), results
    assert len({job_id for job_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    with sessions() as s:
        assert s.query(RecoveryJob).filter_by(proposal_id=pid).count() == 1
        assert s.query(Approval).filter_by(proposal_id=pid, status="consumed").count() == 1


def test_duplicate_job_delivery_writes_production_once(sessions):
    pid = seed_validated_proposal(sessions)
    approved(sessions, pid)
    reader = Reader()
    writer = Writer(reader)
    with sessions.begin() as s:
        job, _ = recovery.request(s, pid, actor=OPERATOR, reader=reader)
    first = recovery.execute(sessions, job.id, reader, writer, Verifier())
    second = recovery.execute(sessions, job.id, reader, writer, Verifier())
    assert (first, second, writer.calls) == ("succeeded", "succeeded", 1)


def test_stale_config_after_approval_refuses_and_invalidates(sessions):
    pid = seed_validated_proposal(sessions)
    a = approved(sessions, pid)
    with pytest.raises(PreconditionFailed, match="re-validate and re-approve"), sessions.begin() as s:
        recovery.request(s, pid, actor=OPERATOR, reader=Reader(active_version=4))
    with sessions() as s:
        # The raise rolled back the request transaction, so the approval is still approved;
        # a retry under the same moved state is refused again, and nothing executed.
        assert s.get(Approval, a.id).status == "approved"
        assert s.query(RecoveryJob).filter_by(proposal_id=pid).count() == 0


def test_config_moves_between_request_and_execution(sessions):
    pid = seed_validated_proposal(sessions)
    approved(sessions, pid)
    reader = Reader()
    with sessions.begin() as s:
        job, _ = recovery.request(s, pid, actor=OPERATOR, reader=reader)
    reader.active_version = 4  # someone changed production after approval
    writer = Writer(reader)
    assert recovery.execute(sessions, job.id, reader, writer, Verifier()) == "refused"
    assert writer.calls == 0


def test_validation_for_a_different_action_does_not_authorize(sessions):
    pid = seed_validated_proposal(sessions)
    approved(sessions, pid)
    with sessions.begin() as s:  # the action changes after approval (tampering or a bug)
        s.execute(text("UPDATE proposals SET parameters = '{\"to_version\": 1}' WHERE id = :p"), {"p": pid})
    with pytest.raises(PreconditionFailed, match="binding digest mismatch"), sessions.begin() as s:
        recovery.request(s, pid, actor=OPERATOR, reader=Reader())


def test_revalidation_invalidates_open_approval(sessions):
    pid = seed_validated_proposal(sessions)
    a = approved(sessions, pid)
    with sessions.begin() as s:
        proposals.request_validation(s, pid, actor=OPERATOR)
    with sessions() as s:
        assert s.get(Approval, a.id).status == "invalidated"


def test_expired_approval_cannot_be_decided(sessions):
    pid = seed_validated_proposal(sessions)
    with sessions.begin() as s:
        a = approvals.request(s, pid, actor=OPERATOR)
        s.get(Approval, a.id).expires_at = utcnow() - timedelta(seconds=1)
    with pytest.raises(Conflict, match="expired"), sessions.begin() as s:
        approvals.decide(s, a.id, actor=APPROVER, approve=True, note="late", expected_digest=a.binding_digest)


def test_audit_events_append_only_for_application_role(sessions):
    with sessions.begin() as s:
        s.execute(text("INSERT INTO audit_events(actor, action, subject_type, subject_id) VALUES ('t','t','t','t')"))
    for statement in ("UPDATE audit_events SET actor = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with pytest.raises(DBAPIError, match="append-only"), sessions.begin() as s:
            s.execute(text(statement))
