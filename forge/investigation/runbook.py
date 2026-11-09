"""Deterministic runbook investigator (no LLM).

What an experienced on-call engineer's runbook would do, expressed as code:
collect a fixed set of signals through the same tool registry the LLM uses
(same permissions, bounds and evidence ledger), then apply explicit rules.

It serves two purposes:

* evaluation baseline #1, against which the LLM investigator is compared;
* a credential-free investigation mode, so CI and demos without an API key still
  exercise the real pipeline on real telemetry. It is labelled ``runbook``
  everywhere; it is never presented as AI output.

Its rules only know generic failure shapes (connect errors, timeouts, 5xx,
config load errors, a recent config change). It knows nothing about specific
lab scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from forge.investigation.engine import InvestigationResult, Outcome, Step, StepRecorder, Usage
from forge.investigation.evidence import EvidenceItem, EvidenceLedger
from forge.investigation.schemas import Category, Diagnosis, Hypothesis
from forge.investigation.toolkit import ToolContext, ToolRegistry

WINDOW = 15
MIN_FAILURES = 3.0
FAILED_ORDERS = 'sum by (reason) (increase(shop_checkout_orders_total{status="failed"}[15m]))'
DEPENDENCY_OUTCOMES = 'sum by (dependency, outcome) (increase(shop_dependency_requests_total{service="checkout"}[15m]))'
CONFIG_ERRORS = "sum(increase(shop_runtime_config_load_errors_total[15m]))"
DEPENDENCY_P95 = (
    "histogram_quantile(0.95, sum by (le, dependency) "
    '(rate(shop_dependency_request_duration_seconds_bucket{service="checkout"}[5m])))'
)


@dataclass
class _Signals:
    failures: EvidenceItem
    outcomes: EvidenceItem
    config_errors: EvidenceItem
    readiness: EvidenceItem
    endpoints: EvidenceItem
    changes: EvidenceItem


def _series(item: EvidenceItem) -> list[dict[str, Any]]:
    return (item.result.data or {}).get("series", []) if item.ok else []


Component = Literal["checkout", "inventory", "payment", "postgres", "unknown"]
Confidence = Literal["low", "medium", "high"]
_COMPONENTS = ("checkout", "inventory", "payment", "postgres")


def _component(name: str) -> Component:
    return cast(Component, name) if name in _COMPONENTS else "unknown"


def _total(item: EvidenceItem) -> float:
    return float(sum(s["last"] for s in _series(item)))


def _failing_dependency(outcomes: EvidenceItem) -> tuple[str, str, float] | None:
    """(dependency, outcome, count) with the most non-success calls, if any."""
    worst = None
    for s in _series(outcomes):
        labels = s["labels"]
        if labels.get("outcome") == "success" or s["last"] <= 0:
            continue
        if worst is None or s["last"] > worst[2]:
            worst = (labels.get("dependency", "unknown"), labels.get("outcome", "unknown"), s["last"])
    return worst


class RunbookInvestigator:
    name = "runbook"

    def __init__(self, tools: ToolRegistry, ctx: ToolContext) -> None:
        self.tools, self.ctx = tools, ctx

    def run(self, incident: dict[str, Any], recorder: StepRecorder | None = None) -> InvestigationResult:
        recorder = recorder or StepRecorder()
        ledger = EvidenceLedger(on_add=recorder.on_evidence)
        usage = Usage()
        steps: list[Step] = []

        def call(summary: str, tool: str, **args: Any) -> EvidenceItem:
            usage.tool_calls += 1
            item = ledger.add(self.tools.execute(tool, args, self.ctx))
            s = Step("tool_call", summary, tool=tool, evidence_id=item.label)
            steps.append(s)
            recorder.on_step(s)
            return item

        sig = _Signals(
            failures=call("failed checkouts by reason", "query_metrics", query=FAILED_ORDERS, window_minutes=WINDOW),
            outcomes=call(
                "checkout dependency call outcomes",
                "query_metrics",
                query=DEPENDENCY_OUTCOMES,
                window_minutes=WINDOW,
            ),
            config_errors=call(
                "runtime config load errors", "query_metrics", query=CONFIG_ERRORS, window_minutes=WINDOW
            ),
            readiness=call("readiness of every service", "run_allowlisted_diagnostic", name="service_readiness"),
            endpoints=call(
                "TCP reachability of configured endpoints",
                "run_allowlisted_diagnostic",
                name="tcp_connect_configured_endpoints",
            ),
            changes=call("recent configuration changes", "get_recent_changes", window_hours=2),
        )
        diagnosis = self._diagnose(sig, call)
        conclusion = Step(
            "decision",
            f"runbook conclusion: {diagnosis.outcome}"
            + (f" ({diagnosis.top.category} on {diagnosis.top.component})" if diagnosis.top else ""),
        )
        steps.append(conclusion)
        recorder.on_step(conclusion)
        outcome: Outcome = "insufficient_evidence" if diagnosis.outcome == "insufficient_evidence" else "completed"
        return InvestigationResult(outcome, diagnosis, usage, None, steps, ledger.items())

    # ------------------------------------------------------------------ rules
    def _diagnose(self, sig: _Signals, call: Any) -> Diagnosis:
        core = [sig.failures, sig.outcomes, sig.readiness, sig.endpoints]
        if not all(i.ok for i in core):
            failed = [i.label for i in core if not i.ok]
            return Diagnosis(
                outcome="insufficient_evidence",
                limitations=[f"required signals unavailable: {failed}"],
                next_steps=["restore telemetry access and re-run the investigation"],
            )

        if _total(sig.config_errors) > 0:
            return self._invalid_config(sig)

        failures = _total(sig.failures)
        worst = _failing_dependency(sig.outcomes)
        if failures < MIN_FAILURES and worst is None:
            return Diagnosis(
                outcome="no_incident",
                limitations=[f"{failures:.0f} failed checkouts in {WINDOW}m (threshold {MIN_FAILURES:.0f})"],
            )
        if worst is None:
            return Diagnosis(
                outcome="insufficient_evidence",
                limitations=["checkouts fail but no dependency call failures are recorded"],
                next_steps=["inspect checkout error logs and traces"],
            )

        dependency, outcome, _count = worst
        if outcome in ("connect_error", "http_404"):
            return self._unreachable(sig, dependency, call)
        if outcome == "timeout":
            p95 = call("dependency latency p95", "query_metrics", query=DEPENDENCY_P95, window_minutes=WINDOW)
            return _single(
                Category.DEPENDENCY_LATENCY,
                dependency,
                "medium",
                f"Calls from checkout to {dependency} are timing out.",
                [sig.outcomes.label, p95.label],
                [sig.readiness.label],
            )
        if outcome == "http_5xx":
            logs = call(
                f"{dependency} error logs",
                "search_logs",
                service=dependency,
                level="error",
                window_minutes=WINDOW,
            )
            return _single(
                Category.DEPENDENCY_ERRORS,
                dependency,
                "medium",
                f"{dependency} is answering checkout with server errors.",
                [sig.outcomes.label, logs.label],
                [],
            )
        return Diagnosis(
            outcome="insufficient_evidence",
            limitations=[f"unrecognised failure shape: {dependency}/{outcome}"],
        )

    def _invalid_config(self, sig: _Signals) -> Diagnosis:
        evidence = [sig.config_errors.label, sig.changes.label]
        setting = None
        return _single(
            Category.INVALID_CONFIGURATION,
            "checkout",
            "high" if sig.changes.ok else "medium",
            "Checkout cannot load its runtime configuration (validation failures).",
            evidence,
            [],
            setting,
        )

    def _unreachable(self, sig: _Signals, dependency: str, call: Any) -> Diagnosis:
        url_key = f"{dependency}_url"
        endpoint = ((sig.endpoints.result.data or {}).get("results") or {}).get(url_key, {})
        dep_ready = bool(((sig.readiness.result.data or {}).get("results") or {}).get(dependency, {}).get("ready"))
        change = _latest_checkout_change(sig.changes)
        diff_item = None
        changed_key = False
        if change is not None and change.get("from_version") and change.get("to_version"):
            diff_item = call(
                "diff of the latest checkout config change",
                "get_configuration_diff",
                service="checkout",
                from_version=change["from_version"],
                to_version=change["to_version"],
            )
            changes = (diff_item.result.data or {}).get("changes", []) if diff_item.ok else []
            changed_key = any(c.get("key") == url_key for c in changes)

        config_evidence = [sig.outcomes.label, sig.endpoints.label, sig.readiness.label]
        if diff_item is not None:
            config_evidence.append(diff_item.label)
        configured = endpoint.get("url", "unknown")
        if dep_ready and endpoint.get("reachable") is False:
            config_hyp = Hypothesis(
                rank=1,
                category=Category.CONFIGURATION_ERROR,
                component="checkout",
                faulty_setting=url_key,
                confidence="high" if changed_key else "medium",
                evidence_ids=config_evidence,
                summary=(
                    f"{dependency} is healthy but checkout's configured endpoint {configured} refuses "
                    f"connections" + (f"; {url_key} changed in the latest config change." if changed_key else ".")
                ),
            )
            dep_hyp = Hypothesis(
                rank=2,
                category=Category.DEPENDENCY_UNAVAILABLE,
                component=_component(dependency),
                confidence="low",
                evidence_ids=[sig.outcomes.label],
                contradicting_evidence_ids=[sig.readiness.label],
                summary=f"{dependency} itself is down (contradicted: it reports ready).",
            )
            return Diagnosis(
                outcome="diagnosed",
                hypotheses=[config_hyp, dep_hyp],
                affected=["checkout", "customer checkout journey"],
                limitations=["runbook rules; no log or trace correlation performed"],
                next_steps=[f"restore checkout {url_key} to its previous value"],
            )
        if not dep_ready:
            return _single(
                Category.DEPENDENCY_UNAVAILABLE,
                dependency,
                "medium",
                f"{dependency} is not ready and checkout cannot connect to it.",
                [sig.outcomes.label, sig.readiness.label],
                [],
            )
        return Diagnosis(
            outcome="insufficient_evidence",
            limitations=[f"connect errors to {dependency}, but its configured endpoint is reachable"],
            next_steps=["check network policy/DNS between checkout and the dependency"],
        )


def _latest_checkout_change(changes: EvidenceItem) -> dict[str, Any] | None:
    events = (changes.result.data or {}).get("changes", []) if changes.ok else []
    checkout = [e for e in events if e.get("service") == "checkout" and e.get("kind") == "config_change"]
    return max(checkout, key=lambda e: e.get("occurred_at", ""), default=None)


def _single(
    category: Category,
    component: str,
    confidence: Confidence,
    summary: str,
    evidence: list[str],
    contradicting: list[str],
    setting: str | None = None,
) -> Diagnosis:
    return Diagnosis(
        outcome="diagnosed",
        affected=["checkout", "customer checkout journey"],
        limitations=["runbook rules; no log or trace correlation performed"],
        hypotheses=[
            Hypothesis(
                rank=1,
                category=category,
                component=_component(component),
                confidence=confidence,
                summary=summary,  # type: ignore[arg-type]
                evidence_ids=evidence,
                contradicting_evidence_ids=contradicting,
                faulty_setting=setting,
            )
        ],
    )
