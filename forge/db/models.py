"""Control-plane schema (forge database).

Constraints that carry correctness guarantees (do not remove without
replacing the guarantee):

* ``uq_recovery_jobs_proposal``: at most one recovery job per proposal, so a
  duplicate execute request returns the existing job instead of running twice.
* ``uq_recovery_jobs_approval``: an approval is consumed by at most one job.
* ``uq_approvals_one_open``: at most one pending/approved approval per proposal.
* ``uq_evidence_label``: evidence labels (E1, E2…) are unique per investigation.
* audit_events is append-only via trigger (application-level guarantee; a
  database superuser can still alter it, so this is not tamper-proof storage).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16))  # manual | detector
    signal: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    synthetic_traffic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic locking
    __mapper_args__ = {"version_id_col": version}


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))  # llm | runbook
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class InvestigationStep(Base):
    __tablename__ = "investigation_steps"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(String(48))
    evidence_label: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("investigation_id", "label", name="uq_evidence_label"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    label: Mapped[str] = mapped_column(String(8))
    tool: Mapped[str] = mapped_column(String(48))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ok: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    injection_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"))
    action_type: Mapped[str] = mapped_column(String(48))
    target: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expected_active_version: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)  # effect, side effects, procedures, evidence ids
    status: Mapped[str] = mapped_column(String(24))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    status: Mapped[str] = mapped_column(String(24))  # queued | running | passed | failed | not_reproducible | error
    production_version: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requested_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index(
            "uq_approvals_one_open",
            "proposal_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    validation_run_id: Mapped[str] = mapped_column(ForeignKey("validation_runs.id"))
    binding: Mapped[dict[str, Any]] = mapped_column(JSONB)
    binding_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TS)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    note: Mapped[str | None] = mapped_column(Text)


class RecoveryJob(Base):
    __tablename__ = "recovery_jobs"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_recovery_jobs_proposal"),
        UniqueConstraint("approval_id", name="uq_recovery_jobs_approval"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"))
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"))
    status: Mapped[str] = mapped_column(String(24))
    requested_by: Mapped[str] = mapped_column(String(64))
    config_version_before: Mapped[int | None] = mapped_column(Integer)
    config_version_after: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Job(Base):
    """Background work queue (investigations, validations, recoveries)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_ready", "status", "run_after"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    run_after: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(40), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
