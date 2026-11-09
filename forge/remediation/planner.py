"""Deterministic remediation planning from an allowlisted catalogue.

The investigator (LLM or runbook) produces a diagnosis; it never writes an
action. This planner maps the top hypothesis onto one catalogue action and
computes the exact parameters from real configuration history. That keeps the
model's influence to "which hypothesis is most likely", which humans review,
and keeps the action itself fully determined by code and data.

Catalogue (what is implemented):

* ``rollback_config_version``: roll a service's runtime config forward to a
  copy of a specific earlier version (the last version whose value of the
  faulty setting differed, or the last valid version).

``restore_previous_config`` (always the immediately previous version) is also
supported for operator-initiated proposals. A feature-flag reset is not in the
catalogue yet because the demo shop has no feature flags (see known issues).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from forge.investigation.schemas import Category, Diagnosis
from shop.common.config_schema import config_diff, validate_config

SUPPORTED_TARGETS = frozenset({"checkout"})
ACTIONS = frozenset({"rollback_config_version", "restore_previous_config"})
CONFIG_CATEGORIES = frozenset({Category.CONFIGURATION_ERROR, Category.INVALID_CONFIGURATION})


@dataclass(frozen=True)
class ConfigVersionView:
    version: int
    payload: dict[str, Any]
    author: str = ""


@dataclass(frozen=True)
class ProposalDraft:
    action_type: str
    target: str
    parameters: dict[str, Any]
    expected_active_version: int
    expected_effect: list[dict[str, Any]]
    side_effects: list[dict[str, Any]]
    evidence_ids: list[str]
    preconditions: list[str]
    validation_procedure: list[str]
    rollback_procedure: dict[str, Any]
    approval_requirement: str = "one approver (role approver or admin), not the requester; expires in 15 minutes"
    rationale: str = ""


@dataclass(frozen=True)
class NoAction:
    reason: str
    escalate: bool = True
    details: dict[str, Any] = field(default_factory=dict)


def _valid(service: str, payload: dict[str, Any]) -> bool:
    try:
        validate_config(service, payload)
    except (ValidationError, ValueError):
        return False
    return True


def _find_target(
    history: list[ConfigVersionView], active: ConfigVersionView, setting: str | None, service: str
) -> ConfigVersionView | None:
    """Newest earlier valid version that undoes the faulty setting (or any newest valid one)."""
    for candidate in sorted(history, key=lambda v: v.version, reverse=True):
        if candidate.version >= active.version or not _valid(service, candidate.payload):
            continue
        if setting is None or candidate.payload.get(setting) != active.payload.get(setting):
            return candidate
    return None


def plan_remediation(
    diagnosis: Diagnosis, active: ConfigVersionView, history: list[ConfigVersionView]
) -> ProposalDraft | NoAction:
    top = diagnosis.top
    if diagnosis.outcome != "diagnosed" or top is None:
        return NoAction(f"no remediation for outcome {diagnosis.outcome!r}", escalate=False)
    if top.category not in CONFIG_CATEGORIES:
        return NoAction(f"no catalogue action for {top.category}; escalate to a human responder")
    if top.component not in SUPPORTED_TARGETS:
        return NoAction(f"component {top.component!r} has no supported config actions")
    if top.confidence == "low":
        return NoAction("top hypothesis has low confidence; gather more evidence before acting")

    service = top.component
    setting = top.faulty_setting if top.category == Category.CONFIGURATION_ERROR else None
    target = _find_target(history, active, setting, service)
    if target is None:
        return NoAction(
            "no earlier valid config version restores the suspected setting",
            details={"setting": setting, "active_version": active.version},
        )

    diff = config_diff(active.payload, target.payload)
    effect = [c for c in diff if setting is None or c["key"] == setting]
    side_effects = [c for c in diff if c not in effect]
    return ProposalDraft(
        action_type="rollback_config_version",
        target=service,
        parameters={"to_version": target.version},
        expected_active_version=active.version,
        expected_effect=effect,
        side_effects=side_effects,
        evidence_ids=list(top.evidence_ids),
        preconditions=[
            f"{service} active config version is still v{active.version}",
            f"v{target.version} passes {service} config schema validation",
            "no other recovery job is executing for this proposal",
            "approval is approved, unexpired, and bound to this exact action",
        ],
        validation_procedure=[
            "reset the validation sandbox to baseline",
            f"apply production v{active.version} payload in the sandbox; the checkout journey must FAIL (reproduction)",
            f"apply the v{target.version} payload in the sandbox; the checkout journey must SUCCEED (recovery)",
            "regression: declined card returns 402; inventory and payment ready",
        ],
        rollback_procedure={
            "action_type": "rollback_config_version",
            "target": service,
            "parameters": {"to_version": active.version},
            "description": f"roll forward to a copy of v{active.version} (the pre-repair state)",
        },
        rationale=top.summary,
    )
