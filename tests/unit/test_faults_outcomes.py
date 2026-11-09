import pytest
from pydantic import ValidationError

from shop.common.context import accept_request_id, parse_synthetic
from shop.common.faults import FaultConfig, FaultInjector
from shop.common.outcomes import Outcome, classify_status, is_retryable


def test_no_fault_by_default():
    d = FaultInjector().decide()
    assert d.delay_s == 0 and d.error_status is None


def test_error_rate_is_seeded_and_reproducible():
    cfg = FaultConfig(error_rate=0.3, seed=7)
    a, b = FaultInjector(), FaultInjector()
    a.set(cfg)
    b.set(cfg)
    seq_a = [a.decide().error_status for _ in range(200)]
    seq_b = [b.decide().error_status for _ in range(200)]
    assert seq_a == seq_b
    rate = sum(1 for s in seq_a if s) / len(seq_a)
    assert 0.2 < rate < 0.4


def test_latency_and_clear():
    inj = FaultInjector()
    inj.set(FaultConfig(latency_ms=250))
    assert inj.decide().delay_s == 0.25
    inj.clear()
    assert not inj.config.active


def test_fault_config_bounds():
    with pytest.raises(ValidationError):
        FaultConfig(error_rate=1.5)
    with pytest.raises(ValidationError):
        FaultConfig(error_status=404)


@pytest.mark.parametrize(
    "status,outcome",
    [
        (200, Outcome.SUCCESS),
        (201, Outcome.SUCCESS),
        (404, Outcome.HTTP_404),
        (422, Outcome.HTTP_4XX),
        (503, Outcome.HTTP_5XX),
    ],
)
def test_classify_status(status, outcome):
    assert classify_status(status) == outcome


def test_retryable_outcomes():
    assert is_retryable(Outcome.CONNECT_ERROR)
    assert is_retryable(Outcome.TIMEOUT)
    assert not is_retryable(Outcome.HTTP_404)
    assert not is_retryable(Outcome.HTTP_4XX)


def test_request_id_validation_blocks_log_injection():
    assert accept_request_id("journey-abc_1.2") == "journey-abc_1.2"
    minted = accept_request_id('x"\n{"level":"ERROR"}')
    assert minted.startswith("req_")
    assert accept_request_id(None).startswith("req_")


def test_parse_synthetic():
    assert parse_synthetic("1") and parse_synthetic("TRUE")
    assert not parse_synthetic(None) and not parse_synthetic("0")
