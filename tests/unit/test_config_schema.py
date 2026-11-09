import pytest
from pydantic import ValidationError

from shop.common.config_schema import CheckoutConfig, config_diff, validate_config

BASE = {"payment_url": "http://payment:8002", "inventory_url": "http://inventory:8001"}


def test_valid_config_and_trailing_slash_normalised():
    cfg = CheckoutConfig.model_validate({**BASE, "payment_url": "http://payment:8002/"})
    assert cfg.payment_url == "http://payment:8002"


def test_wrong_port_is_still_schema_valid():
    # The S1 fault is a *plausible* value: schema validation cannot catch it,
    # which is exactly why it needs investigation rather than input validation.
    CheckoutConfig.model_validate({**BASE, "payment_url": "http://payment:8020"})


@pytest.mark.parametrize(
    "url",
    [
        "ftp://payment:8002",
        "http://",
        "http://u:p@payment:8002",
        "http://payment:99999",
        "http://payment:8002/?x=1",
    ],
)
def test_bad_urls_rejected(url):
    with pytest.raises(ValidationError):
        CheckoutConfig.model_validate({**BASE, "payment_url": url})


def test_unknown_keys_rejected():
    with pytest.raises(ValidationError):
        CheckoutConfig.model_validate({**BASE, "debug": True})


def test_unknown_service_rejected():
    with pytest.raises(ValueError):
        validate_config("nope", BASE)


def test_config_diff():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1, "b": 5, "d": 4}
    assert config_diff(old, new) == [
        {"key": "b", "op": "changed", "old": 2, "new": 5},
        {"key": "c", "op": "removed", "old": 3},
        {"key": "d", "op": "added", "new": 4},
    ]
