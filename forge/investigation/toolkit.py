"""Bounded, permission-checked execution of investigator tools.

Every tool call, whether it comes from the LLM or from the runbook investigator,
goes through ``ToolRegistry.execute``, which enforces in order:

1. the tool exists,
2. the caller holds the tool's scope,
3. arguments validate against the tool's pydantic input model (bounds live there),
4. the handler finishes within the tool's timeout,
5. output is redacted and capped in size.

Failures come back as a ``ToolResult`` with a structured error rather than an
exception, because a failed query is itself evidence the investigator should
see and reason about ("Loki unavailable" ≠ "no error logs").
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from shop.common.redaction import redact

log = logging.getLogger("forge.tools")

MAX_RESULT_BYTES = 12_000
_MAX_LIST_ITEMS_AFTER_TRUNCATION = 10


class ToolError(Exception):
    """Raised by handlers for expected failures (backend down, not found, ...)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolContext:
    scopes: frozenset[str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    scope: str
    handler: Callable[[Any], dict[str, Any]]
    timeout_s: float = 8.0


@dataclass
class ToolResult:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    truncated: bool = False
    duration_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """What the model sees for this result."""
        if self.ok:
            return {"ok": True, "truncated": self.truncated, "data": self.data}
        return {"ok": False, "error": self.error}


def _cap_size(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Shrink list-valued fields until the JSON fits ``MAX_RESULT_BYTES``."""
    if len(json.dumps(data, default=str)) <= MAX_RESULT_BYTES:
        return data, False
    shrunk = dict(data)
    for key, value in data.items():
        if isinstance(value, list) and len(value) > _MAX_LIST_ITEMS_AFTER_TRUNCATION:
            shrunk[key] = value[:_MAX_LIST_ITEMS_AFTER_TRUNCATION]
            shrunk[f"{key}_omitted"] = len(value) - _MAX_LIST_ITEMS_AFTER_TRUNCATION
    text = json.dumps(shrunk, default=str)
    if len(text) <= MAX_RESULT_BYTES:
        return shrunk, True
    return {"preview": text[:MAX_RESULT_BYTES], "note": "result truncated to size limit"}, True


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {s.name: s for s in specs}
        if len(self._specs) != len(specs):
            raise ValueError("duplicate tool names")
        # A small pool is enough: tools run one at a time per investigation.
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="forge-tool")

    @property
    def names(self) -> list[str]:
        return sorted(self._specs)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "input_schema": s.input_model.model_json_schema()}
            for s in sorted(self._specs.values(), key=lambda s: s.name)
        ]

    def execute(self, name: str, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.perf_counter()
        result = self._execute(name, arguments, ctx)
        result.duration_ms = round((time.perf_counter() - start) * 1000, 1)
        return result

    def _execute(self, name: str, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return _error(name, arguments, "unknown_tool", f"no tool named {name!r}; available: {self.names}")
        if spec.scope not in ctx.scopes:
            return _error(name, arguments, "permission_denied", f"caller lacks scope {spec.scope!r}")
        try:
            parsed = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors())
            return _error(name, arguments, "invalid_arguments", problems[:500])

        future = self._pool.submit(spec.handler, parsed)
        try:
            data = future.result(timeout=spec.timeout_s)
        except FutureTimeout:
            # The worker thread cannot be killed; handlers also use their own
            # HTTP timeouts, so this is a backstop that frees the investigation.
            return _error(name, arguments, "timeout", f"tool exceeded {spec.timeout_s}s", retryable=True)
        except ToolError as exc:
            return _error(name, arguments, exc.code, exc.message, retryable=exc.retryable)
        except Exception as exc:  # noqa: BLE001 - surfaced as evidence and logged, never swallowed
            log.exception("tool %s raised unexpectedly", name)
            return _error(name, arguments, "internal_tool_error", f"{type(exc).__name__}: {exc}"[:300])

        capped, truncated = _cap_size(redact(data))
        return ToolResult(name, parsed.model_dump(mode="json"), True, data=capped, truncated=truncated)


def _error(name: str, arguments: dict[str, Any], code: str, message: str, *, retryable: bool = False) -> ToolResult:
    return ToolResult(name, redact(arguments), False, error={"code": code, "message": message, "retryable": retryable})
