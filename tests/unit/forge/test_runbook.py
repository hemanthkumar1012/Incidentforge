from forge.investigation.evidence import EvidenceLedger, check_claims
from forge.investigation.runbook import RunbookInvestigator
from forge.investigation.tool_catalog import INVESTIGATOR_SCOPES
from forge.investigation.toolkit import ToolContext
from tests.unit.forge.fakes import FakeTelemetry, series

CTX = ToolContext(INVESTIGATOR_SCOPES)


def run(t):
    return RunbookInvestigator(t.registry(), CTX).run({"title": "t"})


def claims_ok(result):
    ledger = EvidenceLedger()
    for item in result.evidence:
        ledger.add(item.result)
    return check_claims(result.diagnosis, ledger)


def test_caller_misconfiguration_beats_dependency_down():
    result = run(FakeTelemetry.config_endpoint_fault())
    top = result.diagnosis.top
    assert (top.category, top.component, top.faulty_setting, top.confidence) == (
        "configuration_error",
        "checkout",
        "payment_url",
        "high",
    )
    second = result.diagnosis.hypotheses[1]
    assert second.component == "payment" and second.contradicting_evidence_ids
    assert claims_ok(result) == []


def test_dependency_actually_down():
    t = FakeTelemetry.config_endpoint_fault()
    t.versions.pop(2)
    t.active_version, t.events = 1, []
    t.ready["payment"] = False
    t.listening.discard(("payment", 8002))
    top = run(t).diagnosis.top
    assert (top.category, top.component) == ("dependency_unavailable", "payment")


def test_timeouts_mean_latency():
    t = FakeTelemetry.healthy()
    t.metric_responses["checkout_orders_total"] = [series({"reason": "inventory_unavailable"}, 12)]
    t.metric_responses["dependency_requests_total"] = [series({"dependency": "inventory", "outcome": "timeout"}, 30)]
    top = run(t).diagnosis.top
    assert (top.category, top.component) == ("dependency_latency", "inventory")


def test_healthy_system_is_no_incident():
    assert run(FakeTelemetry.healthy()).diagnosis.outcome == "no_incident"


def test_missing_telemetry_is_insufficient_evidence():
    t = FakeTelemetry.config_endpoint_fault()
    t.unavailable.add("metrics")
    result = run(t)
    assert result.outcome == "insufficient_evidence"
    assert "unavailable" in result.diagnosis.limitations[0]
