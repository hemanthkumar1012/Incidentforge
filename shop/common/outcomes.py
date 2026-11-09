"""Classification of outbound dependency call outcomes.

The outcome label is the most important evidence signal for distinguishing a
failing dependency (``http_5xx``/``timeout`` from a reachable service) from an
upstream configuration error (``connect_error``/``http_404`` toward a target the
dependency does not serve). Kept as a closed set so Prometheus label
cardinality is bounded.
"""

from __future__ import annotations

from enum import StrEnum


class Outcome(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    CONNECT_ERROR = "connect_error"
    HTTP_404 = "http_404"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    BAD_RESPONSE = "bad_response"


def classify_status(status_code: int) -> Outcome:
    if 200 <= status_code < 300:
        return Outcome.SUCCESS
    if status_code == 404:
        return Outcome.HTTP_404
    if 400 <= status_code < 500:
        return Outcome.HTTP_4XX
    if status_code >= 500:
        return Outcome.HTTP_5XX
    return Outcome.BAD_RESPONSE


def is_retryable(outcome: Outcome) -> bool:
    return outcome in {Outcome.TIMEOUT, Outcome.CONNECT_ERROR, Outcome.HTTP_5XX}
