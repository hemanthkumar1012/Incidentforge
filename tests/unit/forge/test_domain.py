from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.binding import ActionBinding
from forge.domain.policy import (
    Actor,
    ApprovalSnapshot,
    Permission,
    Role,
    approval_decision_refusals,
    execution_refusals,
    has_permission,
)
from forge.domain.states import APPROVAL, INCIDENT, INVESTIGATION, PROPOSAL, RECOVERY, InvalidTransition

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
BINDING = ActionBinding("rollback_config_version", "checkout", {"to_version": 1}, 2, "val_1")


@pytest.mark.parametrize(
    "machine,current,target",
    [
        (APPROVAL, "rejected", "approved"),
        (APPROVAL, "consumed", "approved"),
        (APPROVAL, "pending", "consumed"),  # must be approved first
        (RECOVERY, "requested", "succeeded"),  # cannot skip execution and verification
        (RECOVERY, "succeeded", "executing"),
        (PROPOSAL, "proposed", "executed"),  # never execute an unvalidated proposal
        (PROPOSAL, "not_reproducible", "executed"),
        (INVESTIGATION, "completed", "running"),
        (INCIDENT, "resolved", "open"),
    ],
)
def test_illegal_transitions_raise(machine, current, target):
    with pytest.raises(InvalidTransition):
        machine.check(current, target)


def test_legal_paths():
    for a, b in [("pending", "approved"), ("approved", "consumed")]:
        APPROVAL.check(a, b)
    for a, b in [("requested", "executing"), ("executing", "verifying"), ("verifying", "succeeded")]:
        RECOVERY.check(a, b)
    assert all(APPROVAL.is_terminal(s) for s in ("rejected", "expired", "invalidated", "consumed"))


def test_binding_digest_changes_with_any_bound_field():
    base = BINDING.digest()
    assert ActionBinding("rollback_config_version", "checkout", {"to_version": 1}, 2, "val_1").digest() == base
    for changed in [
        ActionBinding("restore_previous_config", "checkout", {"to_version": 1}, 2, "val_1"),
        ActionBinding("rollback_config_version", "inventory", {"to_version": 1}, 2, "val_1"),
        ActionBinding("rollback_config_version", "checkout", {"to_version": 3}, 2, "val_1"),
        ActionBinding("rollback_config_version", "checkout", {"to_version": 1}, 3, "val_1"),
        ActionBinding("rollback_config_version", "checkout", {"to_version": 1}, 2, "val_2"),
    ]:
        assert changed.digest() != base


def test_binding_digest_independent_of_parameter_order():
    a = ActionBinding("x", "t", {"a": 1, "b": 2}, 1, "v")
    b = ActionBinding("x", "t", {"b": 2, "a": 1}, 1, "v")
    assert a.digest() == b.digest()


def snapshot(**kw):
    defaults = dict(
        status="pending",
        requested_by="olivia",
        binding_digest=BINDING.digest(),
        expires_at=NOW + timedelta(minutes=15),
    )
    return ApprovalSnapshot(**{**defaults, **kw})


def test_approver_can_decide_pending_request():
    assert approval_decision_refusals(Actor("arun", Role.APPROVER), snapshot(), NOW) == []


@pytest.mark.parametrize(
    "actor,snap,expected",
    [
        (Actor("olivia", Role.ADMIN), snapshot(), "separation of duties"),
        (Actor("ola", Role.OPERATOR), snapshot(), "cannot decide approvals"),
        (Actor("vic", Role.VIEWER), snapshot(), "cannot decide approvals"),
        (Actor("arun", Role.APPROVER), snapshot(status="approved"), "not pending"),
        (Actor("arun", Role.APPROVER), snapshot(expires_at=NOW), "expired"),
    ],
)
def test_approval_refusals(actor, snap, expected):
    reasons = approval_decision_refusals(actor, snap, NOW)
    assert any(expected in r for r in reasons), reasons


def test_execution_allowed_only_when_everything_matches():
    ok = execution_refusals(
        snapshot(status="approved"),
        current_binding_digest=BINDING.digest(),
        expected_active_version=2,
        current_active_version=2,
        now=NOW,
    )
    assert ok == []


def test_execution_refused_when_config_moved_after_approval():
    reasons = execution_refusals(
        snapshot(status="approved"),
        current_binding_digest=BINDING.digest(),
        expected_active_version=2,
        current_active_version=3,
        now=NOW,
    )
    assert any("re-validate and re-approve" in r for r in reasons)


def test_execution_refused_on_tampered_action_or_expiry():
    tampered = ActionBinding("rollback_config_version", "checkout", {"to_version": 0}, 2, "val_1").digest()
    reasons = execution_refusals(
        snapshot(status="approved", expires_at=NOW - timedelta(seconds=1)),
        current_binding_digest=tampered,
        expected_active_version=2,
        current_active_version=2,
        now=NOW,
    )
    assert any("binding digest mismatch" in r for r in reasons)
    assert any("expired" in r for r in reasons)


def test_role_permissions():
    assert has_permission(Role.OPERATOR, Permission.EXECUTE_RECOVERY)
    assert not has_permission(Role.OPERATOR, Permission.DECIDE_APPROVAL)
    assert not has_permission(Role.APPROVER, Permission.EXECUTE_RECOVERY)
    assert not has_permission(Role.VIEWER, Permission.REGISTER_INCIDENT)
    assert all(has_permission(Role.ADMIN, p) for p in Permission)
