"""Deterministic provider for automated tests. NOT a real model.

It replays a fixed list of replies (or raises scripted errors) and records
what it was sent, so tests can assert on prompts and on engine behaviour
(retries, malformed output, budgets). Investigations run with it are labelled
``provider=scripted-test`` and it cannot be selected by deployment settings.
Passing tests with this adapter says nothing about whether the live Gemini
integration works; that is what tests/live is for.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from forge.investigation.providers.base import Message, ModelReply


class ScriptedProvider:
    name = "scripted-test"
    model = "none"

    def __init__(self, script: Iterable[str | Exception | ModelReply]) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, list[Message]]] = []

    def generate(self, system: str, messages: list[Message], response_schema: dict[str, Any]) -> ModelReply:
        self.calls.append((system, list(messages)))
        if not self._script:
            raise AssertionError("ScriptedProvider ran out of scripted replies")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, ModelReply):
            return step
        return ModelReply(text=step, input_tokens=100, output_tokens=20)
