"""Live Gemini smoke test. Opt-in: needs GEMINI_API_KEY and network.

    GEMINI_API_KEY=... python3 -m pytest tests/live -m live -q

What it verifies: the REST call, structured JSON output accepted by our schema, tool
calling through the real model, and claim checking, against in-memory telemetry
shaped like a caller misconfiguration. What it does NOT verify: diagnosis quality on
real telemetry (that is the evaluation runner's job). Runbook acceptance passing says
nothing about this integration.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="no GEMINI_API_KEY")]


def test_gemini_investigation_produces_valid_supported_output():
    from forge.investigation.engine import Budget, LLMInvestigator
    from forge.investigation.providers.gemini import GeminiProvider
    from forge.investigation.tool_catalog import INVESTIGATOR_SCOPES
    from forge.investigation.toolkit import ToolContext
    from tests.unit.forge.fakes import FakeTelemetry

    provider = GeminiProvider(os.environ["GEMINI_API_KEY"], os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    inv = LLMInvestigator(
        provider,
        FakeTelemetry.config_endpoint_fault().registry(),
        ToolContext(INVESTIGATOR_SCOPES),
        Budget(max_model_turns=10, max_tool_calls=8, max_seconds=180),
    )
    result = inv.run({"title": "checkout failures", "signal": "failure ratio above threshold"})
    assert result.outcome in ("completed", "insufficient_evidence"), result.failure_reason
    assert result.usage.tool_calls >= 1 and result.usage.input_tokens > 0
    print({"outcome": result.outcome, "top": result.diagnosis and result.diagnosis.top, "usage": vars(result.usage)})
