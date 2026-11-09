import pytest

from forge.investigation.schemas import Diagnosis, Hypothesis
from forge.remediation.planner import ConfigVersionView, NoAction, ProposalDraft, plan_remediation
from forge.validation.runner import (
    CheckResult,
    SandboxMappingRejected,
    SandboxUnavailable,
    to_sandbox_payload,
    validate_rollback,
)

BASE = {"payment_url": "http://payment:8002", "inventory_url": "http://inventory:8001"}
V1 = ConfigVersionView(1, dict(BASE))
V2 = ConfigVersionView(2, {**BASE, "payment_timeout_s": 3.0})
V3 = ConfigVersionView(3, {**BASE, "payment_timeout_s": 3.0, "payment_url": "http://payment:8020"})
HOSTS = {"payment": "sandbox-payment", "inventory": "sandbox-inventory"}


def diagnosis(category="configuration_error", component="checkout", setting="payment_url", confidence="high"):
    return Diagnosis(
        outcome="diagnosed",
        hypotheses=[
            Hypothesis(
                rank=1,
                category=category,
                component=component,
                faulty_setting=setting,
                confidence=confidence,
                summary="checkout calls payment on a port where nothing listens",
                evidence_ids=["E1", "E2"],
            )
        ],
    )


def test_rollback_targets_last_version_with_different_setting():
    draft = plan_remediation(diagnosis(), V3, [V1, V2, V3])
    assert isinstance(draft, ProposalDraft)
    # v2 already had the good payment_url and keeps the unrelated timeout change.
    assert draft.parameters == {"to_version": 2} and draft.expected_active_version == 3
    assert draft.expected_effect == [
        {"key": "payment_url", "op": "changed", "old": "http://payment:8020", "new": "http://payment:8002"}
    ]
    assert draft.side_effects == []
    assert draft.rollback_procedure["parameters"] == {"to_version": 3}
    assert draft.evidence_ids == ["E1", "E2"]


def test_side_effects_are_disclosed():
    v2bad = ConfigVersionView(2, {**BASE, "payment_url": "http://payment:8020", "payment_timeout_s": 5.0})
    draft = plan_remediation(diagnosis(), v2bad, [V1, v2bad])
    assert draft.parameters == {"to_version": 1}
    assert [c["key"] for c in draft.side_effects] == ["payment_timeout_s"]


def test_invalid_earlier_versions_are_skipped():
    broken = ConfigVersionView(2, {"payment_url": "not a url"})
    draft = plan_remediation(
        diagnosis(category="invalid_configuration", setting=None),
        ConfigVersionView(3, {"payment_url": 5}),
        [V1, broken],
    )
    assert draft.parameters == {"to_version": 1}


def test_no_action_cases():
    cases = [
        (diagnosis(category="dependency_latency"), "no catalogue action"),
        (diagnosis(component="payment"), "no supported config actions"),
        (diagnosis(confidence="low"), "low confidence"),
        (Diagnosis(outcome="insufficient_evidence"), "no remediation"),
    ]
    for diag, reason in cases:
        result = plan_remediation(diag, V3, [V1, V2, V3])
        assert isinstance(result, NoAction) and reason in result.reason
    nothing_earlier = plan_remediation(diagnosis(), V1, [V1])
    assert isinstance(nothing_earlier, NoAction)


def test_sandbox_mapping_uses_allowlist_and_keeps_port_and_path():
    mapped = to_sandbox_payload(
        {"payment_url": "http://payment:8020/v1", "inventory_url": "http://invntory:8001", "currency": "USD"},
        HOSTS,
    )
    assert mapped == {
        "payment_url": "http://sandbox-payment:8020/v1",
        "inventory_url": "http://unresolvable.invalid:8001",  # typo host: fails, reaches nothing
        "currency": "USD",
    }


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:5432", "http://127.0.0.1:8002", "http://localhost:8002", "http://[::1]:8002"]
)
def test_sandbox_mapping_rejects_addresses(url):
    with pytest.raises(SandboxMappingRejected):
        to_sandbox_payload({"payment_url": url}, HOSTS)


class FakeSandbox:
    """Checkout works iff payment_url points at the sandbox payment port 8002."""

    def __init__(self, broken_check=None, fail_reset=False):
        self.payload = {}
        self.broken_check = broken_check
        self.fail_reset = fail_reset
        self.applied = []
        self.resets = 0

    def reset(self):
        self.resets += 1
        self.payload = {}
        if self.fail_reset:
            raise SandboxUnavailable("sandbox database unreachable")

    def apply_config(self, service, payload):
        self.payload = payload
        self.applied.append(payload)
        return len(self.applied)

    def run_check(self, name):
        if name == self.broken_check:
            return CheckResult(name, False, "regressed")
        if name == "checkout_journey":
            return CheckResult(name, self.payload.get("payment_url") == "http://sandbox-payment:8002")
        return CheckResult(name, True)


def test_rejected_mapping_is_validation_error_not_pass():
    bad = {**V3.payload, "payment_url": "http://10.1.1.1:80"}
    assert validate_rollback(FakeSandbox(), "checkout", bad, V2.payload, HOSTS).verdict == "error"


def test_each_validation_starts_from_reset_state():
    sandbox = FakeSandbox()
    validate_rollback(sandbox, "checkout", V3.payload, V2.payload, HOSTS)
    validate_rollback(sandbox, "checkout", V3.payload, V2.payload, HOSTS)
    assert sandbox.resets == 2


def test_validation_passes_when_reproduced_and_repaired():
    sandbox = FakeSandbox()
    report = validate_rollback(sandbox, "checkout", V3.payload, V2.payload, HOSTS)
    assert report.verdict == "passed"
    assert [s["phase"] for s in report.steps] == ["setup", "reproduction", "recovery", "regression"]
    assert sandbox.applied[0]["payment_url"] == "http://sandbox-payment:8020"


def test_not_reproducible_is_not_verified():
    report = validate_rollback(FakeSandbox(), "checkout", V1.payload, V1.payload, HOSTS)
    assert report.verdict == "not_reproducible"
    assert any("not verified" in u for u in report.uncertainty)


def test_regression_failure_fails_validation():
    report = validate_rollback(
        FakeSandbox(broken_check="declined_card_returns_402"), "checkout", V3.payload, V2.payload, HOSTS
    )
    assert report.verdict == "failed"


def test_repair_that_does_not_fix_fails_validation():
    still_broken = {**BASE, "payment_url": "http://payment:9999"}
    assert validate_rollback(FakeSandbox(), "checkout", V3.payload, still_broken, HOSTS).verdict == "failed"


def test_sandbox_unavailable_is_error():
    assert validate_rollback(FakeSandbox(fail_reset=True), "checkout", V3.payload, V2.payload, HOSTS).verdict == "error"
