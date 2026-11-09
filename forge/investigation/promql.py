"""Validation of model-supplied PromQL.

The investigator may write its own PromQL (fixed query templates would make
the "tool-using investigator" no different from the runbook). It is read-only
by nature, so the risks are cost and scope: an expensive query, or reading
metrics outside the shop. The rule is simple and explainable: after removing
string literals, label matchers and ``by``/``without`` groupings, every
remaining identifier must be a PromQL function/keyword or a known shop metric.
"""

from __future__ import annotations

import re

SHOP_METRICS = frozenset(
    {
        "shop_http_requests_total",
        "shop_http_request_duration_seconds",
        "shop_dependency_requests_total",
        "shop_dependency_request_duration_seconds",
        "shop_checkout_orders_total",
        "shop_runtime_config_version",
        "shop_runtime_config_load_errors_total",
        "up",
    }
)
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")

PROMQL_WORDS = frozenset(
    {
        # aggregations
        "sum",
        "avg",
        "min",
        "max",
        "count",
        "stddev",
        "stdvar",
        "topk",
        "bottomk",
        "quantile",
        "group",
        # functions
        "rate",
        "irate",
        "increase",
        "delta",
        "idelta",
        "histogram_quantile",
        "abs",
        "ceil",
        "floor",
        "round",
        "clamp_min",
        "clamp_max",
        "absent",
        "absent_over_time",
        "avg_over_time",
        "max_over_time",
        "min_over_time",
        "sum_over_time",
        "count_over_time",
        "last_over_time",
        "time",
        "vector",
        "scalar",
        "sort",
        "sort_desc",
        "label_replace",
        "resets",
        "changes",
        # keywords and set operators
        "by",
        "without",
        "on",
        "ignoring",
        "group_left",
        "group_right",
        "offset",
        "bool",
        "and",
        "or",
        "unless",
    }
)

MAX_QUERY_CHARS = 400
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_MATCHERS = re.compile(r"\{[^{}]*\}")
_GROUPING = re.compile(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)")
_DURATION = re.compile(r"\[[^\]]*\]")
_NUMBER = re.compile(r"(?<![A-Za-z_:])\d+(?:\.\d+)?(?:e[+-]?\d+)?(?:ms|[smhdwy])?")
_IDENT = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")


class PromQLRejected(ValueError):
    pass


def _known_metric(token: str) -> bool:
    if token in SHOP_METRICS:
        return True
    return any(token.endswith(s) and token[: -len(s)] in SHOP_METRICS for s in _HISTOGRAM_SUFFIXES)


def check_promql(query: str) -> str:
    query = query.strip()
    if not query:
        raise PromQLRejected("query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise PromQLRejected(f"query longer than {MAX_QUERY_CHARS} characters")
    stripped = _STRING.sub('""', query)
    stripped = _MATCHERS.sub("", stripped)
    stripped = _GROUPING.sub(r"\1", stripped)
    stripped = _DURATION.sub("", stripped)
    stripped = _NUMBER.sub("", stripped)
    metrics = []
    for token in _IDENT.findall(stripped):
        if token.lower() in PROMQL_WORDS:
            continue
        if not _known_metric(token):
            raise PromQLRejected(f"identifier {token!r} is not an allowed shop metric; allowed: {sorted(SHOP_METRICS)}")
        metrics.append(token)
    if not metrics:
        raise PromQLRejected("query must reference at least one shop metric")
    return query
