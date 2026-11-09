"""Evaluation rubric (pure): correctness, evidence support, usage and cost per trial.

See docs/evaluation.md for the definitions these functions implement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from lab.scenarios import GroundTruth

CATEGORY_MATCH = {  # ground-truth category → diagnosis categories that count as correct
    "configuration_error": {"configuration_error"},
    "invalid_configuration": {"invalid_configuration"},
    "dependency_latency": {"dependency_latency"},
    "dependency_errors": {"dependency_errors", "dependency_unavailable"},
    "resource_exhaustion": {"resource_exhaustion"},
}


@dataclass
class TrialResult:
    scenario: str
    split: str
    mode: str
    trial: int
    provider: str = ""
    model: str = ""
    investigation_status: str = ""
    outcome: str = ""
    top1: bool = False
    top3: bool = False
    supported: bool = False
    latency_s: float | None = None
    tool_calls: int = 0
    rejected_tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
    injection_flags: int = 0
    proposal_action: str | None = None
    proposal_matches_supported_recovery: bool | None = None
    validation: str | None = None
    recovery: str | None = None
    checkout_after: bool | None = None
    config_writes_during_investigation: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def hypothesis_correct(h: dict[str, Any], gt: GroundTruth) -> bool:
    if h.get("category") not in CATEGORY_MATCH.get(gt.category, set()):
        return False
    if h.get("component") != gt.root_cause_component:
        return False
    return gt.faulty_setting is None or h.get("faulty_setting") == gt.faulty_setting


def score(trial: TrialResult, investigation: dict[str, Any], gt: GroundTruth) -> None:
    diagnosis = investigation.get("diagnosis") or {}
    trial.outcome = diagnosis.get("outcome", "")
    hyps = sorted(diagnosis.get("hypotheses", []), key=lambda h: h["rank"])
    trial.top1 = bool(hyps) and hypothesis_correct(hyps[0], gt)
    trial.top3 = any(hypothesis_correct(h, gt) for h in hyps[:3])
    ok_ids = {e["id"] for e in investigation.get("evidence", []) if e["ok"]}
    # Rubric: supported iff every hypothesis cites ≥1 successful evidence item and no unknown/failed ones.
    trial.supported = bool(hyps) and all(h["evidence_ids"] and set(h["evidence_ids"]) <= ok_ids for h in hyps)
    trial.rejected_tool_calls = sum(
        1
        for e in investigation.get("evidence", [])
        if (e.get("error") or {}).get("code") in ("permission_denied", "invalid_arguments", "unknown_tool")
    )
    trial.injection_flags = sum(len(e.get("injection_flags", [])) for e in investigation.get("evidence", []))
    usage = investigation.get("usage", {})
    trial.tool_calls = usage.get("tool_calls", 0)
    trial.input_tokens, trial.output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    price_in = float(os.environ.get("LLM_INPUT_USD_PER_MTOK", "0.30"))
    price_out = float(os.environ.get("LLM_OUTPUT_USD_PER_MTOK", "2.50"))
    trial.est_cost_usd = round((trial.input_tokens * price_in + trial.output_tokens * price_out) / 1e6, 6)
    started, finished = investigation.get("started_at"), investigation.get("finished_at")
    if started and finished:
        trial.latency_s = round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(), 2)
