import copy

import pytest

from lab.controller import ActiveConfig, InjectionRecord, LabController, LabError
from lab.scenarios import SCENARIO_DIR, load_all

BASELINE = {
    "payment_url": "http://payment:8002",
    "inventory_url": "http://inventory:8001",
    "payment_timeout_s": 2.0,
    "inventory_timeout_s": 2.0,
    "max_items_per_order": 20,
    "currency": "USD",
}


class FakeConfig:
    def __init__(self):
        self.versions = [(1, copy.deepcopy(BASELINE))]
        self.writes = []

    def active(self, service):
        v, p = self.versions[-1]
        return ActiveConfig(v, copy.deepcopy(p))

    def apply(self, service, payload, *, actor, reason, summary, validate):
        v = self.versions[-1][0] + 1
        self.versions.append((v, copy.deepcopy(payload)))
        self.writes.append({"actor": actor, "summary": summary, "validate": validate})
        return v


class FakeAdmin:
    def __init__(self):
        self.calls = []

    def set_fault(self, service, fault):
        self.calls.append(("set", service))

    def clear_fault(self, service):
        self.calls.append(("clear", service))

    def restock(self):
        self.calls.append(("restock",))


class FakeStore:
    def __init__(self):
        self.rows = []

    def active(self):
        for r in reversed(self.rows):
            if r["ended"] is None:
                return InjectionRecord(r["id"], r["scenario"], r["details"])
        return None

    def start(self, scenario, details):
        row = {
            "id": len(self.rows) + 1,
            "scenario": scenario.id,
            "details": details,
            "ended": None,
            "ground_truth": scenario.ground_truth.model_dump(),
        }
        self.rows.append(row)
        return InjectionRecord(row["id"], scenario.id, details)

    def end(self, injection_id, outcome):
        self.rows[injection_id - 1]["ended"] = outcome


def make():
    cfg, admin, store = FakeConfig(), FakeAdmin(), FakeStore()
    ctl = LabController(load_all(), cfg, admin, store, {"checkout": BASELINE})
    return ctl, cfg, admin, store


def test_all_scenario_files_validate():
    scenarios = load_all()
    assert "S1" in scenarios
    assert all(s.synthetic for s in scenarios.values())
    assert SCENARIO_DIR.is_dir()


def test_inject_s1_changes_only_payment_url_with_neutral_change_record():
    ctl, cfg, _, store = make()
    rec = ctl.inject("S1")
    v, payload = cfg.versions[-1]
    assert payload["payment_url"] == "http://payment:8020"
    assert {k: payload[k] for k in payload if k != "payment_url"} == {
        k: BASELINE[k] for k in BASELINE if k != "payment_url"
    }
    assert rec.details == {
        "injection_type": "config_patch",
        "service": "checkout",
        "from_version": 1,
        "to_version": 2,
    }
    # The visible change record must not leak the scenario or its diagnosis.
    w = cfg.writes[-1]
    for leaked in ("S1", "payment", "endpoint", "fault", "inject", "8020"):
        assert leaked.lower() not in w["summary"].lower()
        assert leaked.lower() not in w["actor"].lower()
    assert store.rows[0]["ground_truth"]["category"] == "configuration_error"


def test_double_injection_refused():
    ctl, *_ = make()
    ctl.inject("S1")
    with pytest.raises(LabError, match="still active"):
        ctl.inject("S1")


def test_unknown_scenario_refused():
    ctl, *_ = make()
    with pytest.raises(LabError):
        ctl.inject("S99")


def test_cleanup_restores_baseline_and_is_idempotent():
    ctl, cfg, _, store = make()
    ctl.inject("S1")
    out = ctl.cleanup()
    assert out["cleaned"] == "S1"
    assert cfg.versions[-1][1] == BASELINE and cfg.versions[-1][0] == 3
    assert store.active() is None
    assert ctl.cleanup() == {"cleaned": None}
    assert len(cfg.versions) == 3


def test_cleanup_after_external_rollback_writes_nothing():
    """If remediation already restored the baseline, cleanup must not add a version."""
    ctl, cfg, *_ = make()
    ctl.inject("S1")
    cfg.apply("checkout", BASELINE, actor="remediator", reason="r", summary="s", validate=True)
    n = len(cfg.versions)
    ctl.cleanup()
    assert len(cfg.versions) == n


def test_reset_from_any_state():
    ctl, cfg, admin, store = make()
    ctl.inject("S1")
    report = ctl.reset()
    assert report["cleanup"]["cleaned"] == "S1"
    assert cfg.versions[-1][1] == BASELINE
    assert ("clear", "payment") in admin.calls and ("clear", "inventory") in admin.calls
    assert ("restock",) in admin.calls
    assert store.active() is None
    # reset on a healthy system is a no-op for config
    n = len(cfg.versions)
    ctl.reset()
    assert len(cfg.versions) == n


def test_evaluation_rubric():
    from lab.scoring import TrialResult, hypothesis_correct, score

    gt = load_all()["S1"].ground_truth
    right = {"category": "configuration_error", "component": "checkout", "faulty_setting": "payment_url"}
    assert hypothesis_correct(right, gt)
    assert not hypothesis_correct({**right, "component": "payment"}, gt)
    assert not hypothesis_correct({**right, "faulty_setting": "inventory_url"}, gt)
    assert not hypothesis_correct({**right, "category": "dependency_unavailable"}, gt)
    inv = {
        "diagnosis": {
            "outcome": "diagnosed",
            "hypotheses": [
                {"rank": 1, **right, "evidence_ids": ["E1", "E2"]},
                {"rank": 2, "category": "dependency_unavailable", "component": "payment", "evidence_ids": ["E9"]},
            ],
        },
        "evidence": [{"id": "E1", "ok": True}, {"id": "E2", "ok": True}],
        "usage": {"tool_calls": 7, "input_tokens": 1000, "output_tokens": 100},
        "started_at": "2026-11-08T10:00:00+00:00",
        "finished_at": "2026-11-08T10:00:12+00:00",
    }
    t = TrialResult("S1", "development", "llm", 1)
    score(t, inv, gt)
    assert t.top1 and t.top3 and t.latency_s == 12.0
    assert not t.supported  # hypothesis 2 cites E9, which does not exist
    assert t.est_cost_usd > 0
