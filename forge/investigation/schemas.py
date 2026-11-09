"""Structured model output and diagnosis schemas.

``ModelDecision`` is deliberately flat (no unions, tool arguments as a JSON
string) because provider JSON-schema support varies; flat schemas validate the
same way everywhere. Tool arguments are validated afterwards against each
tool's own input model.

``summary`` is a short, user-visible decision note ("checking payment
connection errors"). It is not a reasoning transcript, and the prompt does not
ask for one.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KNOWN_COMPONENTS = ("checkout", "inventory", "payment", "postgres", "unknown")


class Category(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEPENDENCY_LATENCY = "dependency_latency"
    DEPENDENCY_ERRORS = "dependency_errors"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    UNKNOWN = "unknown"


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=5)
    category: Category
    component: Literal["checkout", "inventory", "payment", "postgres", "unknown"]
    faulty_setting: str | None = Field(default=None, max_length=64)
    summary: str = Field(min_length=10, max_length=500)
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    contradicting_evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["diagnosed", "insufficient_evidence", "no_incident"]
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    affected: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    next_steps: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _consistent(self) -> Diagnosis:
        if self.outcome == "diagnosed" and not self.hypotheses:
            raise ValueError("a diagnosed outcome needs at least one hypothesis")
        ranks = sorted(h.rank for h in self.hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hypothesis ranks must be 1..n without gaps or duplicates")
        return self

    @property
    def top(self) -> Hypothesis | None:
        return min(self.hypotheses, key=lambda h: h.rank) if self.hypotheses else None


class ModelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["call_tool", "final"]
    summary: str = Field(min_length=3, max_length=300)
    tool_name: str | None = None
    tool_arguments_json: str | None = Field(default=None, max_length=2_000)
    diagnosis: Diagnosis | None = None

    @model_validator(mode="after")
    def _shape(self) -> ModelDecision:
        if self.decision == "call_tool":
            if not self.tool_name:
                raise ValueError("call_tool requires tool_name")
            if self.diagnosis is not None:
                raise ValueError("call_tool must not include a diagnosis")
        else:
            if self.diagnosis is None:
                raise ValueError("final requires a diagnosis")
            if self.tool_name:
                raise ValueError("final must not include tool_name")
        return self

    @field_validator("tool_arguments_json")
    @classmethod
    def _json_object(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"tool_arguments_json is not valid JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("tool_arguments_json must encode a JSON object")
        return v

    def tool_arguments(self) -> dict[str, Any]:
        return json.loads(self.tool_arguments_json) if self.tool_arguments_json else {}
