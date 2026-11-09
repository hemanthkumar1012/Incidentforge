"""Gemini provider over the public REST API (``generateContent``).

Uses plain HTTP rather than the SDK so the request is explicit and the error
mapping is under our control. Structured output is requested with
``responseMimeType: application/json`` and ``responseJsonSchema``; the engine
still validates every reply with pydantic, because a schema hint is not a
guarantee.

The API key is sent in the ``x-goog-api-key`` header (never in the URL, so it
cannot leak into access logs).
"""

from __future__ import annotations

from typing import Any

import httpx

from forge.investigation.providers.base import (
    Message,
    ModelReply,
    ProviderError,
    ProviderTransientError,
)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 60.0,
        temperature: float = 0.1,
        http: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.model = model
        self._key = api_key
        self._temperature = temperature
        self._http = http or httpx.Client(timeout=timeout_s)

    def generate(self, system: str, messages: list[Message], response_schema: dict[str, Any]) -> ModelReply:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": m.role, "parts": [{"text": m.text}]} for m in messages],
            "generationConfig": {
                "temperature": self._temperature,
                "responseMimeType": "application/json",
                "responseJsonSchema": response_schema,
            },
        }
        try:
            resp = self._http.post(
                f"{API_BASE}/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._key},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTransientError(f"Gemini request timed out: {type(exc).__name__}") from exc
        except httpx.TransportError as exc:
            raise ProviderTransientError(f"Gemini transport error: {type(exc).__name__}") from exc

        if resp.status_code in TRANSIENT_STATUSES:
            raise ProviderTransientError(f"Gemini returned {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini returned {resp.status_code}: {resp.text[:300]}")
        return self._parse(resp.json())

    @staticmethod
    def _parse(data: dict[str, Any]) -> ModelReply:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ProviderError(f"Gemini returned no candidates ({reason})")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"}:
            raise ProviderError(f"Gemini stopped generation: {finish}")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
        return ModelReply(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
        )
