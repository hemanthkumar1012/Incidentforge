"""Provider abstraction for the LLM investigator.

A provider turns (system prompt, conversation, JSON schema) into one JSON text
reply plus token usage. Everything else (tool execution, validation, budgets,
retries) lives in the engine, so providers stay small and swappable.

Error taxonomy, used by the engine's retry policy:

* ``ProviderTransientError`` timeouts, 429, 5xx, so retry with backoff
* ``ProviderError``          auth, bad request, safety block, so fail the investigation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


class ProviderError(RuntimeError):
    pass


class ProviderTransientError(ProviderError):
    pass


@dataclass(frozen=True)
class Message:
    role: Literal["user", "model"]
    text: str


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, messages: list[Message], response_schema: dict[str, Any]) -> ModelReply: ...
