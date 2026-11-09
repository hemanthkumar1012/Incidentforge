from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.detection import evaluate
from forge.domain.policy import Role
from forge.identity import (
    AuthError,
    decode_token,
    hash_password,
    issue_token,
    parse_bootstrap,
    verify_password,
)

SECRET = "x" * 40


def test_password_hash_roundtrip_and_salt():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("correct horse battery", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("anything", "md5$abc")


def test_token_roundtrip_expiry_and_tamper():
    token = issue_token("arun", "approver", SECRET)
    assert decode_token(token, SECRET) == "arun"
    with pytest.raises(AuthError, match="invalid"):
        decode_token(token, "y" * 40)
    old = issue_token("arun", "approver", SECRET, now=datetime.now(UTC) - timedelta(hours=9))
    with pytest.raises(AuthError, match="expired"):
        decode_token(old, SECRET)
    with pytest.raises(AuthError):
        decode_token(token[:-2] + "aa", SECRET)


def test_none_algorithm_token_rejected():
    import jwt

    forged = jwt.encode({"sub": "mallory", "iat": 0, "exp": 9_999_999_999}, key="", algorithm="none")
    with pytest.raises(AuthError):
        decode_token(forged, SECRET)


def test_bootstrap_parsing():
    users = parse_bootstrap("olivia:operator:operator-pass-1, arun:approver:approver-pass-1")
    assert users == [("olivia", Role.OPERATOR, "operator-pass-1"), ("arun", Role.APPROVER, "approver-pass-1")]
    with pytest.raises(ValueError, match="at least 12"):
        parse_bootstrap("x:viewer:short")
    with pytest.raises(ValueError):
        parse_bootstrap("x:superuser:long-enough-pass")


def s(status, value):
    return {"labels": {"status": status}, "values": [[1, "0"], [2, str(value)]]}


def test_detector_threshold_and_ratio():
    assert evaluate([s("failed", 12), s("confirmed", 8)], 5) == {
        "metric": "shop_checkout_orders_total",
        "window": "5m",
        "failed": 12.0,
        "confirmed": 8.0,
        "failure_ratio": 0.6,
    }
    assert evaluate([s("failed", 3), s("confirmed", 0)], 5) is None  # below absolute threshold
    assert evaluate([s("failed", 6), s("confirmed", 200)], 5) is None  # declines/noise under 20%
    assert evaluate([], 5) is None
