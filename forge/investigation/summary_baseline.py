"""Evaluation baseline #2: an LLM given a fixed telemetry summary, no tools.

It collects exactly the runbook's fixed signal set (same registry, same bounds,
same evidence ledger), then makes ONE model call asking for a diagnosis that
cites those evidence IDs. Comparing it with the tool-using investigator isolates
the value of letting the model choose its own queries.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from forge.investigation.engine import InvestigationResult, Outcome, Step, StepRecorder, Usage
from forge.investigation.evidence import EvidenceLedger, check_claims
from forge.investigation.prompts import DECISION_SCHEMA, SYSTEM_PROMPT, correction
from forge.investigation.providers.base import LLMProvider, Message, ProviderError
from forge.investigation.runbook import CONFIG_ERRORS, DEPENDENCY_OUTCOMES, FAILED_ORDERS, WINDOW
from forge.investigation.schemas import ModelDecision
from forge.investigation.toolkit import ToolContext, ToolRegistry

FIXED_SIGNALS: list[tuple[str, dict[str, Any]]] = [
    ("query_metrics", {"query": FAILED_ORDERS, "window_minutes": WINDOW}),
    ("query_metrics", {"query": DEPENDENCY_OUTCOMES, "window_minutes": WINDOW}),
    ("query_metrics", {"query": CONFIG_ERRORS, "window_minutes": WINDOW}),
    ("run_allowlisted_diagnostic", {"name": "service_readiness"}),
    ("run_allowlisted_diagnostic", {"name": "tcp_connect_configured_endpoints"}),
    ("get_recent_changes", {"window_hours": 2}),
    ("search_logs", {"service": "checkout", "level": "warning", "window_minutes": WINDOW, "limit": 10}),
]
INSTRUCTION = (
    "PLATFORM: no tools are available in this mode. Using only the evidence above, reply with a JSON object "
    'whose "decision" is "final" and whose diagnosis cites evidence IDs.'
)


class SummaryBaselineInvestigator:
    name = "llm_summary"

    def __init__(self, provider: LLMProvider, tools: ToolRegistry, ctx: ToolContext) -> None:
        self.provider, self.tools, self.ctx = provider, tools, ctx

    def run(self, incident: dict[str, Any], recorder: StepRecorder | None = None) -> InvestigationResult:
        recorder = recorder or StepRecorder()
        ledger = EvidenceLedger(on_add=recorder.on_evidence)
        usage, steps = Usage(), []
        for tool, args in FIXED_SIGNALS:
            usage.tool_calls += 1
            item = ledger.add(self.tools.execute(tool, args, self.ctx))
            step = Step("tool_call", f"fixed signal: {tool}", tool=tool, evidence_id=item.label)
            steps.append(step)
            recorder.on_step(step)
        blocks = "\n\n".join(item.render() for item in ledger.items())
        messages = [Message("user", f"INCIDENT: {incident}\n\n{blocks}\n\n{INSTRUCTION}")]
        for _attempt in range(2):  # one correction allowed
            try:
                reply = self.provider.generate(SYSTEM_PROMPT, messages, DECISION_SCHEMA)
            except ProviderError as exc:
                return InvestigationResult("failed", None, usage, f"provider error: {exc}", steps, ledger.items())
            usage.model_turns += 1
            usage.input_tokens += reply.input_tokens
            usage.output_tokens += reply.output_tokens
            problem = _problem(reply.text, ledger)
            if problem is None:
                decision = ModelDecision.model_validate_json(reply.text)
                assert decision.diagnosis is not None
                outcome: Outcome = (
                    "insufficient_evidence" if decision.diagnosis.outcome == "insufficient_evidence" else "completed"
                )
                return InvestigationResult(outcome, decision.diagnosis, usage, None, steps, ledger.items())
            usage.invalid_replies += 1
            messages += [Message("model", reply.text), Message("user", correction(problem))]
        return InvestigationResult("failed", None, usage, f"invalid reply: {problem}", steps, ledger.items())


def _problem(text: str, ledger: EvidenceLedger) -> str | None:
    try:
        decision = ModelDecision.model_validate_json(text)
    except ValidationError as exc:
        return f"schema violation: {exc.errors()[0]['msg']}"
    if decision.decision != "final" or decision.diagnosis is None:
        return "this mode requires a final diagnosis"
    problems = check_claims(decision.diagnosis, ledger)
    return "unsupported diagnosis: " + "; ".join(problems) if problems else None
