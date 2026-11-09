"""Redaction of sensitive values before they reach logs or telemetry.

The demo uses only synthetic data, but redaction is applied anyway so that the
logging pipeline behaves the way a real one must, and so that the investigator
(Milestone 2) never receives secrets through log search results.

Pure stdlib: unit-testable without the service dependencies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

# Keys whose values are always removed, matched case-insensitively.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "card_token",
        "card_number",
        "cvv",
        "x-lab-token",
        "cookie",
        "set-cookie",
    }
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Payment test tokens such as tok_test_visa.
    (re.compile(r"\btok_[A-Za-z0-9_]+\b"), "tok_" + REDACTED),
    # Bearer / Basic credentials.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 " + REDACTED),
    # Email addresses.
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # Card-number-like digit runs (13-19 digits, optional spaces/dashes).
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[PAN]"),
    # key=value pairs for sensitive keys inside free text (e.g. URLs, query strings).
    (
        re.compile(r"(?i)\b(password|secret|token|api_key|apikey)=([^\s&]+)"),
        r"\1=" + REDACTED,
    ),
)

_MAX_DEPTH = 8


def redact_text(value: str) -> str:
    """Return ``value`` with sensitive substrings replaced."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact strings, mappings and sequences.

    Values under sensitive keys are replaced wholesale. Depth is bounded so a
    pathological structure cannot cause unbounded recursion.
    """
    if _depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in SENSITIVE_KEYS:
                out[key] = REDACTED
            else:
                out[key] = redact(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    return value
