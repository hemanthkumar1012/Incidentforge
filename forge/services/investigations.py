"""Starting and executing investigations.

``start`` runs in the API request transaction: it creates the investigation,
moves the incident to ``investigating`` and enqueues the job atomically.

``execute`` runs in the worker and manages its own short transactions, so
progress (steps, evidence) is committed as it happens and the UI timeline
updates during a run instead of appearing all at once at the end.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from forge.db.models import Evidence, Incident, Investigation, InvestigationStep
from forge.domain.states import INCIDENT, INVESTIGATION
from forge.investigation.engine import InvestigationResult, Step, StepRecorder
from forge.investigation.evidence import EvidenceItem
from forge.jobs.queue import enqueue
from forge.services import proposals
from forge.services.common import Conflict, audit, get_or_404, move, new_id, utcnow

Mode = Literal["llm", "runbook", "llm_summary"]


class Investigator(Protocol):
    def run(self, incident: dict[str, Any], recorder: StepRecorder | None = None) -> InvestigationResult: ...


class InvestigatorFactory(Protocol):
    def __call__(self, mode: Mode) -> tuple[Investigator, str, str]:
        """Return (investigator, provider name, model name) for ``mode``."""
        ...


def start(session: Session, incident_id: str, *, mode: Mode, actor: str, provider: str, model: str) -> Investigation:
    incident = get_or_404(session, Incident, incident_id)
    running = session.scalar(
        select(func.count())
        .select_from(Investigation)
        .where(Investigation.incident_id == incident_id, Investigation.status.in_(("queued", "running")))
    )
    if running:
        raise Conflict("an investigation is already queued or running for this incident")
    if incident.status != "investigating":
        move(INCIDENT, incident, "investigating")
    inv = Investigation(
        id=new_id("inv"),
        incident_id=incident_id,
        mode=mode,
        provider=provider,
        model=model,
        status="queued",
        created_by=actor,
        usage={},
    )
    session.add(inv)
    session.flush()
    enqueue(session, "investigation", inv.id)
    audit(session, actor, "investigation.started", "investigation", inv.id, incident_id=incident_id, mode=mode)
    return inv


def incident_context(incident: Incident) -> dict[str, Any]:
    """The only incident information the investigator receives (platform-owned fields)."""
    return {
        "incident_id": incident.id,
        "title": incident.title,
        "severity": incident.severity,
        "source": incident.source,
        "opened_at": incident.created_at.isoformat(),
        "signal": incident.signal,
    }


class _Recorder(StepRecorder):
    def __init__(self, sessions: sessionmaker[Session], investigation_id: str) -> None:
        self._sessions, self._id, self._seq = sessions, investigation_id, 0
        super().__init__(on_step=self._step, on_evidence=self._evidence)

    def _step(self, step: Step) -> None:
        self._seq += 1
        with self._sessions.begin() as s:
            s.add(
                InvestigationStep(
                    investigation_id=self._id,
                    seq=self._seq,
                    kind=step.kind,
                    summary=step.summary,
                    tool=step.tool,
                    evidence_label=step.evidence_id,
                )
            )

    def _evidence(self, item: EvidenceItem) -> None:
        r = item.result
        with self._sessions.begin() as s:
            s.add(
                Evidence(
                    investigation_id=self._id,
                    label=item.label,
                    tool=r.tool,
                    arguments=r.arguments,
                    ok=r.ok,
                    data=r.data,
                    error=r.error,
                    summary=item.summary(),
                    injection_flags=item.injection_flags,
                    truncated=r.truncated,
                    duration_ms=r.duration_ms,
                )
            )


_FINAL_STATUS = {
    "completed": "completed",
    "insufficient_evidence": "insufficient_evidence",
    "budget_exhausted": "budget_exhausted",
    "failed": "failed",
}


def execute(
    sessions: sessionmaker[Session],
    investigation_id: str,
    factory: InvestigatorFactory,
    planner_inputs: Callable[[], proposals.PlannerInputs],
) -> str:
    with sessions.begin() as s:
        inv = s.get(Investigation, investigation_id, with_for_update=True)
        if inv is None:
            raise LookupError(f"investigation {investigation_id} vanished")
        if inv.status != "queued":
            return inv.status  # already handled by another attempt
        move(INVESTIGATION, inv, "running")
        inv.started_at = utcnow()
        mode: Mode = inv.mode  # type: ignore[assignment]
        context = incident_context(s.get(Incident, inv.incident_id))  # type: ignore[arg-type]

    investigator, _provider, _model = factory(mode)
    result = investigator.run(context, _Recorder(sessions, investigation_id))

    with sessions.begin() as s:
        inv = s.get(Investigation, investigation_id, with_for_update=True)
        assert inv is not None
        move(INVESTIGATION, inv, _FINAL_STATUS[result.outcome])
        inv.finished_at = utcnow()
        inv.diagnosis = result.diagnosis.model_dump(mode="json") if result.diagnosis else None
        inv.failure_reason = result.failure_reason
        inv.usage = {
            **vars(result.usage),
            "total_tokens": result.usage.total_tokens,
            "evidence_items": len(result.evidence),
        }
        incident = s.get(Incident, inv.incident_id)
        assert incident is not None
        diagnosed = result.diagnosis is not None and result.diagnosis.outcome == "diagnosed"
        if incident.status == "investigating":
            move(INCIDENT, incident, "diagnosed" if diagnosed else "open")
        audit(
            s,
            "investigator",
            "investigation.finished",
            "investigation",
            inv.id,
            incident_id=incident.id,
            outcome=result.outcome,
            failure_reason=result.failure_reason,
        )
        if diagnosed and result.diagnosis is not None:
            proposals.propose_from_diagnosis(s, inv, result.diagnosis, planner_inputs())
        return inv.status
