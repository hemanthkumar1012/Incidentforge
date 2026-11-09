"""Authorization and approval policy (pure functions, no I/O).

Roles are deliberately few:

* ``viewer``   read everything
* ``operator`` register incidents, start investigations, request validation and recovery
* ``approver`` approve or reject an exact action (cannot approve their own request)
* ``admin``    everything, plus settings

The policy returns reasons rather than booleans so the API can show *why*
something is refused, and so tests can assert on the specific rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


class Permission(StrEnum):
    READ = "read"
    REGISTER_INCIDENT = "incident:register"
    CLOSE_INCIDENT = "incident:close"
    RUN_INVESTIGATION = "investigation:run"
    REQUEST_VALIDATION = "proposal:validate"
    REQUEST_APPROVAL = "approval:request"
    DECIDE_APPROVAL = "approval:decide"
    EXECUTE_RECOVERY = "recovery:execute"
    RUN_EVALUATION = "evaluation:run"
    MANAGE_SETTINGS = "settings:manage"


_OPERATOR = {
    Permission.READ,
    Permission.REGISTER_INCIDENT,
    Permission.CLOSE_INCIDENT,
    Permission.RUN_INVESTIGATION,
    Permission.REQUEST_VALIDATION,
    Permission.REQUEST_APPROVAL,
    Permission.EXECUTE_RECOVERY,
    Permission.RUN_EVALUATION,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.OPERATOR: frozenset(_OPERATOR),
    Role.APPROVER: frozenset({Permission.READ, Permission.DECIDE_APPROVAL}),
    Role.ADMIN: frozenset(Permission),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


@dataclass(frozen=True)
class Actor:
    username: str
    role: Role


@dataclass(frozen=True)
class ApprovalSnapshot:
    """What the policy needs to know about an approval request."""

    status: str
    requested_by: str
    binding_digest: str
    expires_at: datetime


def approval_decision_refusals(actor: Actor, approval: ApprovalSnapshot, now: datetime) -> list[str]:
    """Reasons ``actor`` may not approve or reject ``approval`` (empty = allowed)."""
    reasons: list[str] = []
    if not has_permission(actor.role, Permission.DECIDE_APPROVAL):
        reasons.append(f"role {actor.role} cannot decide approvals")
    if actor.username == approval.requested_by:
        reasons.append("the requester of an action cannot approve it (separation of duties)")
    if approval.status != "pending":
        reasons.append(f"approval is {approval.status}, not pending")
    elif now >= approval.expires_at:
        reasons.append("approval request has expired")
    return reasons


def execution_refusals(
    approval: ApprovalSnapshot,
    *,
    current_binding_digest: str,
    expected_active_version: int,
    current_active_version: int | None,
    now: datetime,
) -> list[str]:
    """Reasons a recovery may not execute under ``approval`` (empty = allowed).

    Checked twice: when the recovery job is requested, and again inside the
    execution transaction right before the config write, because production can
    change in between.
    """
    reasons: list[str] = []
    if approval.status != "approved":
        reasons.append(f"approval is {approval.status}, not approved")
    if now >= approval.expires_at:
        reasons.append("approval has expired")
    if approval.binding_digest != current_binding_digest:
        reasons.append("the action changed after it was approved (binding digest mismatch)")
    if current_active_version != expected_active_version:
        reasons.append(
            f"production config moved from v{expected_active_version} to v{current_active_version} "
            "after approval; re-validate and re-approve"
        )
    return reasons
