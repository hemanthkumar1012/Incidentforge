"""The tool-using LLM investigation loop.

    brief → [model decides → validate → run tool → record evidence]* → diagnosis

Policies, all enforced here and not by the model:

* **Budgets**: model turns, tool calls, total tokens and wall-clock time.
  Hitting any of them ends the run as ``budget_exhausted`` with the evidence
  gathered so far.
* **Transient provider errors** are retried with exponential backoff
  (``provider_retries`` attempts); permanent errors fail the run.
* **Malformed or unsupported output** (schema violation, unknown tool
  arguments, claims citing missing evidence) gets a correction message. After
  ``max_invalid_replies`` rejections the run fails. Rejected replies are
  recorded as steps but never executed.
* **Tool failures** are evidence, not crashes: the model sees the structured
  error and can try something else.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from forge.investigation.evidence import EvidenceItem, EvidenceLedger, check_claims
from forge.investigation.prompts import DECISION_SCHEMA, SYSTEM_PROMPT, correction, incident_brief
from forge.investigation.providers.base import (
    LLMProvider,
    Message,
    ProviderError,
    ProviderTransientError,
)
from forge.investigation.schemas import Diagnosis, ModelDecision
from forge.investigation.toolkit import ToolContext, ToolRegistry

Outcome = Literal["completed", "insufficient_evidence", "budget_exhausted", "failed"]


@dataclass(frozen=True)
class Budget:
    max_model_turns: int = 16
    max_tool_calls: int = 12
    max_total_tokens: int = 200_000
    max_seconds: float = 240.0
    max_invalid_replies: int = 3
    provider_retries: int = 3
    retry_base_delay_s: float = 1.0


@dataclass
class Usage:
    model_turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    invalid_replies: int = 0
    provider_retries: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Step:
    kind: Literal["decision", "tool_call", "rejected_reply", "provider_retry", "note"]
    summary: str
    tool: str | None = None
    evidence_id: str | None = None


@dataclass
class InvestigationResult:
    outcome: Outcome
    diagnosis: Diagnosis | None
    usage: Usage
    failure_reason: str | None = None
    steps: list[Step] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)


class StepRecorder:
    """Receives progress as it happens so the UI timeline updates during a run."""

    def __init__(
        self,
        on_step: Callable[[Step], None] | None = None,
        on_evidence: Callable[[EvidenceItem], None] | None = None,
    ) -> None:
        self.on_step = on_step or (lambda s: None)
        self.on_evidence = on_evidence


class _BudgetExhausted(Exception):
    pass


class LLMInvestigator:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        ctx: ToolContext,
        budget: Budget | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider, self.tools, self.ctx = provider, tools, ctx
        self.budget = budget or Budget()
        self._sleep, self._clock = sleep, clock

    def run(self, incident: dict[str, Any], recorder: StepRecorder | None = None) -> InvestigationResult:
        recorder = recorder or StepRecorder()
        ledger = EvidenceLedger(on_add=recorder.on_evidence)
        result = self._run(incident, recorder, ledger)
        result.evidence = ledger.items()
        return result

    def _run(self, incident: dict[str, Any], recorder: StepRecorder, ledger: EvidenceLedger) -> InvestigationResult:
        usage = Usage()
        steps: list[Step] = []

        def step(s: Step) -> None:
            steps.append(s)
            recorder.on_step(s)

        messages = [Message("user", incident_brief(incident, self.tools.describe()))]
        started = self._clock()
        try:
            while True:
                self._check_budget(usage, started)
                reply = self._generate(messages, usage, step)
                messages.append(Message("model", reply))
                decision, problem = self._parse(reply, ledger)
                if problem is not None:
                    usage.invalid_replies += 1
                    step(Step("rejected_reply", problem[:300]))
                    if usage.invalid_replies >= self.budget.max_invalid_replies:
                        return InvestigationResult(
                            "failed",
                            None,
                            usage,
                            f"model produced {usage.invalid_replies} invalid replies; last: {problem[:200]}",
                            steps,
                        )
                    messages.append(Message("user", correction(problem)))
                    continue
                assert decision is not None
                if decision.decision == "final":
                    assert decision.diagnosis is not None
                    step(Step("decision", decision.summary))
                    outcome: Outcome = (
                        "insufficient_evidence"
                        if decision.diagnosis.outcome == "insufficient_evidence"
                        else "completed"
                    )
                    return InvestigationResult(outcome, decision.diagnosis, usage, None, steps)
                messages.append(Message("user", self._run_tool(decision, ledger, usage, step)))
        except _BudgetExhausted as exc:
            step(Step("note", str(exc)))
            return InvestigationResult("budget_exhausted", None, usage, str(exc), steps)
        except ProviderError as exc:
            return InvestigationResult("failed", None, usage, f"provider error: {exc}", steps)

    # ------------------------------------------------------------------ helpers
    def _check_budget(self, usage: Usage, started: float) -> None:
        b = self.budget
        if usage.model_turns >= b.max_model_turns:
            raise _BudgetExhausted(f"model turn budget ({b.max_model_turns}) exhausted")
        if usage.total_tokens >= b.max_total_tokens:
            raise _BudgetExhausted(f"token budget ({b.max_total_tokens}) exhausted")
        if self._clock() - started >= b.max_seconds:
            raise _BudgetExhausted(f"time budget ({b.max_seconds:.0f}s) exhausted")

    def _generate(self, messages: list[Message], usage: Usage, step: Callable[[Step], None]) -> str:
        attempt = 0
        while True:
            attempt += 1
            try:
                reply = self.provider.generate(SYSTEM_PROMPT, messages, DECISION_SCHEMA)
            except ProviderTransientError as exc:
                if attempt >= self.budget.provider_retries:
                    raise ProviderError(f"gave up after {attempt} attempts: {exc}") from exc
                usage.provider_retries += 1
                step(Step("provider_retry", f"transient provider error, retrying: {exc}"[:300]))
                self._sleep(self.budget.retry_base_delay_s * 2 ** (attempt - 1))
                continue
            usage.model_turns += 1
            usage.input_tokens += reply.input_tokens
            usage.output_tokens += reply.output_tokens
            return reply.text

    def _parse(self, reply: str, ledger: EvidenceLedger) -> tuple[ModelDecision | None, str | None]:
        try:
            decision = ModelDecision.model_validate_json(reply)
        except ValidationError as exc:
            first = exc.errors()[0]
            return None, f"schema violation at {'.'.join(map(str, first['loc'])) or 'root'}: {first['msg']}"
        if decision.decision == "final":
            assert decision.diagnosis is not None
            problems = check_claims(decision.diagnosis, ledger)
            if problems:
                return None, "unsupported diagnosis: " + "; ".join(problems)
        return decision, None

    def _run_tool(
        self, decision: ModelDecision, ledger: EvidenceLedger, usage: Usage, step: Callable[[Step], None]
    ) -> str:
        if usage.tool_calls >= self.budget.max_tool_calls:
            raise _BudgetExhausted(f"tool call budget ({self.budget.max_tool_calls}) exhausted")
        usage.tool_calls += 1
        assert decision.tool_name is not None
        result = self.tools.execute(decision.tool_name, decision.tool_arguments(), self.ctx)
        item = ledger.add(result)
        step(Step("tool_call", decision.summary, tool=decision.tool_name, evidence_id=item.label))
        remaining = self.budget.max_tool_calls - usage.tool_calls
        return f"{item.render()}\nPLATFORM: {remaining} tool calls remain."
