import pytest

from forge.investigation.promql import PromQLRejected, check_promql
from forge.investigation.tool_catalog import INVESTIGATOR_SCOPES
from forge.investigation.toolkit import MAX_RESULT_BYTES, ToolContext
from tests.unit.forge.fakes import FakeTelemetry

CTX = ToolContext(INVESTIGATOR_SCOPES)


@pytest.mark.parametrize(
    "query",
    [
        'sum by (dependency, outcome) (rate(shop_dependency_requests_total{dependency="payment"}[5m]))',
        "histogram_quantile(0.95, sum by (le) (rate(shop_dependency_request_duration_seconds_bucket[5m])))",
        "increase(shop_checkout_orders_total[10m] offset 5m) > 2",
    ],
)
def test_promql_accepts_shop_metrics(query):
    assert check_promql(query) == query


@pytest.mark.parametrize(
    "query",
    ["node_cpu_seconds_total", "sum(rate(container_memory[5m]))", "", "sum(" * 100 + "up" + ")" * 100],
)
def test_promql_rejects_foreign_metrics_and_oversized(query):
    with pytest.raises(PromQLRejected):
        check_promql(query)


def test_unknown_tool_is_structured_error():
    r = FakeTelemetry.healthy().registry().execute("delete_database", {}, CTX)
    assert not r.ok and r.error["code"] == "unknown_tool"


def test_permission_denied_without_scope():
    r = FakeTelemetry.healthy().registry().execute("get_recent_changes", {}, ToolContext(frozenset({"telemetry:read"})))
    assert not r.ok and r.error["code"] == "permission_denied"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("search_logs", {"service": "checkout", "window_minutes": 600}),  # window bound
        ("search_logs", {"service": "postgres"}),  # not a shop service
        ("search_logs", {"service": "checkout", "contains": "`} |= `x"}),  # LogQL injection attempt
        ("get_trace", {"trace_id": "../../etc/passwd"}),
        ("query_metrics", {"query": "node_load1"}),
        ("search_logs", {"service": "checkout", "unexpected": 1}),  # extra fields forbidden
    ],
)
def test_invalid_arguments_rejected_before_backend(tool, args):
    t = FakeTelemetry.healthy()
    r = t.registry().execute(tool, args, CTX)
    assert not r.ok and r.error["code"] == "invalid_arguments"
    assert t.queries == []


def test_backend_unavailable_is_retryable_error():
    t = FakeTelemetry.healthy()
    t.unavailable.add("metrics")
    r = t.registry().execute("query_metrics", {"query": "up"}, CTX)
    assert not r.ok and r.error == {
        "code": "backend_unavailable",
        "message": "metrics unreachable",
        "retryable": True,
    }


def test_logql_is_built_server_side():
    r = (
        FakeTelemetry.healthy()
        .registry()
        .execute(
            "search_logs",
            {"service": "checkout", "level": "error", "contains": "dependency call failed"},
            CTX,
        )
    )
    assert r.data["logql"] == '{service="checkout", level="error"} |= `dependency call failed`'


def test_log_results_are_redacted_and_size_capped():
    t = FakeTelemetry.healthy()
    line = '{"msg": "charge tok_test_visa for a@b.com", "level": "INFO", "padding": "%s"}' % ("x" * 400)
    t.log_lines = [{"ts": "t", "labels": {}, "line": line}] * 50
    r = t.registry().execute("search_logs", {"service": "checkout", "limit": 50}, CTX)
    text = str(r.data)
    assert "tok_test_visa" not in text and "a@b.com" not in text
    assert len(str(r.data)) < MAX_RESULT_BYTES * 1.2


def test_tcp_diagnostic_only_targets_configured_endpoints():
    t = FakeTelemetry.config_endpoint_fault()
    r = t.registry().execute("run_allowlisted_diagnostic", {"name": "tcp_connect_configured_endpoints"}, CTX)
    assert r.data["results"]["payment_url"]["reachable"] is False
    assert r.data["results"]["inventory_url"]["reachable"] is True
    assert set(r.data["results"]) == {"payment_url", "inventory_url"}


def test_config_diff_and_missing_version():
    reg = FakeTelemetry.config_endpoint_fault().registry()
    r = reg.execute("get_configuration_diff", {"from_version": 1, "to_version": 2}, CTX)
    assert r.data["changes"] == [
        {"key": "payment_url", "op": "changed", "old": "http://payment:8002", "new": "http://payment:8020"}
    ]
    missing = reg.execute("get_configuration_diff", {"from_version": 1, "to_version": 9}, CTX)
    assert missing.error["code"] == "not_found"


def test_tool_timeout(monkeypatch):
    import time

    reg = FakeTelemetry.healthy().registry()
    spec = reg._specs["query_metrics"]
    object.__setattr__(spec, "timeout_s", 0.05)
    object.__setattr__(spec, "handler", lambda a: time.sleep(0.5) or {})
    r = reg.execute("query_metrics", {"query": "up"}, CTX)
    assert not r.ok and r.error["code"] == "timeout"
