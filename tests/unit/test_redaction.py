from shop.common.redaction import REDACTED, redact, redact_text


def test_redacts_card_tokens_emails_and_bearer():
    text = "charge tok_test_visa for a@b.com with Authorization: Bearer abc.def-123"
    out = redact_text(text)
    assert "tok_test_visa" not in out
    assert "a@b.com" not in out
    assert "abc.def-123" not in out
    assert "[EMAIL]" in out


def test_redacts_pan_like_numbers_but_not_short_ids():
    assert "[PAN]" in redact_text("card 4111 1111 1111 1111 used")
    assert redact_text("order 12345 of 8 items") == "order 12345 of 8 items"


def test_redacts_query_string_secrets():
    assert redact_text("GET /x?token=s3cr3t&page=2") == f"GET /x?token={REDACTED}&page=2"


def test_sensitive_keys_are_replaced_recursively():
    data = {
        "card_token": "tok_test_visa",
        "nested": {"Password": "p", "ok": "fine"},
        "list": [{"api_key": "k"}, "x@y.org"],
    }
    out = redact(data)
    assert out["card_token"] == REDACTED
    assert out["nested"]["Password"] == REDACTED
    assert out["nested"]["ok"] == "fine"
    assert out["list"][0]["api_key"] == REDACTED
    assert out["list"][1] == "[EMAIL]"


def test_depth_is_bounded():
    deep: dict = {}
    cur = deep
    for _ in range(50):
        cur["n"] = {}
        cur = cur["n"]
    redact(deep)  # must not raise RecursionError
