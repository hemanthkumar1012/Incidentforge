"""Row → JSON for API responses. Timestamps are ISO-8601 with an explicit UTC offset."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from forge.db import models as m


def ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def incident(i: m.Incident) -> dict[str, Any]:
    return {
        "id": i.id,
        "title": i.title,
        "status": i.status,
        "severity": i.severity,
        "source": i.source,
        "signal": i.signal,
        "synthetic_traffic": i.synthetic_traffic,
        "created_by": i.created_by,
        "created_at": ts(i.created_at),
        "updated_at": ts(i.updated_at),
        "resolved_at": ts(i.resolved_at),
    }


def investigation(v: m.Investigation) -> dict[str, Any]:
    return {
        "id": v.id,
        "incident_id": v.incident_id,
        "mode": v.mode,
        "provider": v.provider,
        "model": v.model,
        "status": v.status,
        "diagnosis": v.diagnosis,
        "usage": v.usage,
        "failure_reason": v.failure_reason,
        "created_by": v.created_by,
        "created_at": ts(v.created_at),
        "started_at": ts(v.started_at),
        "finished_at": ts(v.finished_at),
    }


def step(s: m.InvestigationStep) -> dict[str, Any]:
    return {
        "seq": s.seq,
        "kind": s.kind,
        "summary": s.summary,
        "tool": s.tool,
        "evidence_id": s.evidence_label,
        "created_at": ts(s.created_at),
    }


def evidence(e: m.Evidence) -> dict[str, Any]:
    # ``data`` is untrusted monitored-system content; clients must render it as text.
    return {
        "id": e.label,
        "tool": e.tool,
        "arguments": e.arguments,
        "ok": e.ok,
        "data": e.data,
        "error": e.error,
        "summary": e.summary,
        "injection_flags": e.injection_flags,
        "truncated": e.truncated,
        "duration_ms": e.duration_ms,
        "created_at": ts(e.created_at),
        "trust": "untrusted",
    }


def proposal(p: m.Proposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "incident_id": p.incident_id,
        "investigation_id": p.investigation_id,
        "action_type": p.action_type,
        "target": p.target,
        "parameters": p.parameters,
        "expected_active_version": p.expected_active_version,
        "status": p.status,
        **p.details,
        "created_by": p.created_by,
        "created_at": ts(p.created_at),
    }


def validation(v: m.ValidationRun) -> dict[str, Any]:
    return {
        "id": v.id,
        "proposal_id": v.proposal_id,
        "status": v.status,
        "production_version": v.production_version,
        "report": v.report,
        "requested_by": v.requested_by,
        "created_at": ts(v.created_at),
        "finished_at": ts(v.finished_at),
    }


def approval(a: m.Approval) -> dict[str, Any]:
    return {
        "id": a.id,
        "proposal_id": a.proposal_id,
        "validation_run_id": a.validation_run_id,
        "binding": a.binding,
        "binding_digest": a.binding_digest,
        "status": a.status,
        "requested_by": a.requested_by,
        "requested_at": ts(a.requested_at),
        "expires_at": ts(a.expires_at),
        "decided_by": a.decided_by,
        "decided_at": ts(a.decided_at),
        "note": a.note,
    }


def recovery(r: m.RecoveryJob) -> dict[str, Any]:
    return {
        "id": r.id,
        "proposal_id": r.proposal_id,
        "approval_id": r.approval_id,
        "status": r.status,
        "requested_by": r.requested_by,
        "config_version_before": r.config_version_before,
        "config_version_after": r.config_version_after,
        "result": r.result,
        "created_at": ts(r.created_at),
        "finished_at": ts(r.finished_at),
    }


def audit_event(a: m.AuditEvent) -> dict[str, Any]:
    return {
        "id": a.id,
        "occurred_at": ts(a.occurred_at),
        "actor": a.actor,
        "action": a.action,
        "subject_type": a.subject_type,
        "subject_id": a.subject_id,
        "incident_id": a.incident_id,
        "details": a.details,
    }
