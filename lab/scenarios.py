"""Scenario definitions for the Incident Lab.

Each scenario stores its injection and cleanup procedures, private ground
truth, expected symptoms, supported recovery action and verification checks.
Definitions are validated strictly so a malformed scenario fails at load time
rather than half-way through an injection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

SCENARIO_DIR = Path(__file__).parent / "scenarios"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GroundTruth(_Strict):
    category: Literal[
        "configuration_error",
        "dependency_latency",
        "dependency_errors",
        "invalid_configuration",
        "resource_exhaustion",
    ]
    root_cause_component: str
    faulty_setting: str | None = None
    failing_dependency_is_healthy: bool
    summary: str


class ConfigPatchInjection(_Strict):
    type: Literal["config_patch"]
    service: str
    patch: dict[str, Any]
    actor: str
    summary: str
    reason: str
    validate_config: bool = True


class ServiceFaultInjection(_Strict):
    type: Literal["service_fault"]
    service: Literal["inventory", "payment"]
    fault: dict[str, Any]


Injection = Annotated[ConfigPatchInjection | ServiceFaultInjection, Field(discriminator="type")]


class Cleanup(_Strict):
    type: Literal["restore_baseline_config", "clear_service_fault"]
    service: str


class Recovery(_Strict):
    action_type: Literal["rollback_config_version", "restore_previous_config", "reset_feature_flag"]
    target: str
    description: str


class Verification(_Strict):
    recovery: list[str] = Field(min_length=1)
    regression: list[str] = Field(default_factory=list)


class Scenario(_Strict):
    id: str = Field(pattern=r"^S\d+$")
    title: str
    synthetic: Literal[True]
    split: Literal["development", "heldout"]
    ground_truth: GroundTruth
    expected_symptoms: list[str] = Field(min_length=1)
    injection: Injection
    cleanup: Cleanup
    supported_recovery: Recovery
    verification: Verification


def load_scenario(path: Path) -> Scenario:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    return Scenario.model_validate(data)


def load_all(directory: Path = SCENARIO_DIR) -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    for path in sorted(directory.glob("S*.yaml")):
        sc = load_scenario(path)
        if sc.id != path.stem:
            raise ValueError(f"{path.name}: id {sc.id!r} does not match file name")
        scenarios[sc.id] = sc
    return scenarios
