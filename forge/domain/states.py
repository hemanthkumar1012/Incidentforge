"""Explicit state machines for the control plane.

Every status column in the forge database is driven through one of these
machines. A transition table makes the legal moves reviewable at a glance and
lets the services fail loudly (``InvalidTransition``) instead of writing an
impossible state. Terminal states have no outgoing transitions.

Kept free of persistence so the rules are unit-testable on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InvalidTransition(ValueError):
    def __init__(self, machine: str, current: str, target: str) -> None:
        super().__init__(f"{machine}: cannot move from {current!r} to {target!r}")
        self.machine = machine
        self.current = current
        self.target = target


@dataclass(frozen=True)
class StateMachine:
    name: str
    transitions: dict[str, frozenset[str]]

    def can(self, current: str, target: str) -> bool:
        return target in self.transitions.get(current, frozenset())

    def check(self, current: str, target: str) -> str:
        if not self.can(current, target):
            raise InvalidTransition(self.name, current, target)
        return target

    def is_terminal(self, state: str) -> bool:
        return not self.transitions.get(state)


def _machine(name: str, table: dict[str, set[str]]) -> StateMachine:
    return StateMachine(name, {k: frozenset(v) for k, v in table.items()})


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    DIAGNOSED = "diagnosed"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    CLOSED = "closed"  # closed without a verified repair (false alarm, handled elsewhere)


INCIDENT = _machine(
    "incident",
    {
        "open": {"investigating", "closed"},
        # Investigations can be re-run, so an incident may return to investigating.
        "investigating": {"diagnosed", "open", "closed"},
        "diagnosed": {"investigating", "remediating", "closed"},
        "remediating": {"diagnosed", "resolved", "closed"},
        "resolved": set(),
        "closed": set(),
    },
)


class InvestigationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"


INVESTIGATION = _machine(
    "investigation",
    {
        "queued": {"running", "cancelled"},
        # running -> queued happens when a worker died mid-run and the job is retried.
        "running": {"completed", "insufficient_evidence", "budget_exhausted", "failed", "queued"},
        "completed": set(),
        "insufficient_evidence": set(),
        "budget_exhausted": set(),
        "failed": set(),
        "cancelled": set(),
    },
)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATING = "validating"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    NOT_REPRODUCIBLE = "not_reproducible"
    SUPERSEDED = "superseded"
    EXECUTED = "executed"


PROPOSAL = _machine(
    "proposal",
    {
        "proposed": {"validating", "superseded"},
        "validating": {"validated", "validation_failed", "not_reproducible", "proposed"},
        # A validated proposal can be re-validated if production state moved.
        "validated": {"validating", "executed", "superseded"},
        "validation_failed": {"validating", "superseded"},
        "not_reproducible": {"validating", "superseded"},
        "superseded": set(),
        "executed": set(),
    },
)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"  # bound state changed (config moved, proposal re-validated)
    CONSUMED = "consumed"  # used by exactly one recovery job


APPROVAL = _machine(
    "approval",
    {
        "pending": {"approved", "rejected", "expired", "invalidated"},
        "approved": {"consumed", "expired", "invalidated"},
        "rejected": set(),
        "expired": set(),
        "invalidated": set(),
        "consumed": set(),
    },
)


class RecoveryStatus(StrEnum):
    REQUESTED = "requested"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    VERIFICATION_FAILED = "verification_failed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    REFUSED = "refused"  # preconditions no longer held at execution time


RECOVERY = _machine(
    "recovery",
    {
        "requested": {"executing", "refused"},
        "executing": {"verifying", "failed", "refused"},
        "verifying": {"succeeded", "verification_failed"},
        "verification_failed": {"rolled_back", "failed"},
        "succeeded": set(),
        "rolled_back": set(),
        "failed": set(),
        "refused": set(),
    },
)
