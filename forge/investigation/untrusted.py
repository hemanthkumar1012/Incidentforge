"""Handling of untrusted tool output (prompt-injection defence).

Logs, trace attributes and change descriptions are attacker-influenced: anyone
who can make the shop log a string can put text in front of the model. The
defence is layered:

1. **Capability limits (primary).** The model can only call read-only tools.
   Remediation is chosen by a deterministic planner from an allowlist, then
   validated and human-approved. Injected text cannot cause a write.
2. **Framing.** Tool output is wrapped in explicit evidence delimiters, and the
   system prompt states that anything inside is data. Delimiter look-alikes
   inside the content are neutralised so content cannot "close" the block.
3. **Flagging.** Instruction-like phrases are detected and recorded on the
   evidence item, so reviewers (and the evaluation) can see that injection was
   attempted. Content is not deleted: evidence must stay faithful.

Detection is heuristic, so it is a signal for humans, not a security boundary.
"""

from __future__ import annotations

import json
import re
from typing import Any

OPEN = "<<EVIDENCE"
CLOSE = "<<END EVIDENCE"

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rx, re.IGNORECASE))
    for name, rx in (
        (
            "override_instructions",
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,20}"
            r"\b(instructions?|rules?|prompts?)\b",
        ),
        ("role_reassignment", r"\byou are now\b|\bact as\b.{0,30}\b(admin|system|operator)\b"),
        ("fake_role_marker", r"(^|\n)\s*(system|assistant|developer)\s*:"),
        ("system_prompt_probe", r"\bsystem prompt\b"),
        (
            "action_request",
            r"\b(approve|execute|apply|run)\b.{0,30}\b(remediation|rollback|command|shell|action)\b",
        ),
        ("tool_invocation", r"\bcall[_ ]tool\b|\"decision\"\s*:\s*\"(call_tool|final)\""),
        ("shell_command", r"\b(curl|wget|bash|rm -rf|chmod|sudo)\b"),
        ("delimiter_spoof", r"<<\s*(END\s+)?EVIDENCE"),
    )
)


def detect_injection(text: str) -> list[str]:
    """Names of instruction-like patterns found in ``text`` (empty if none)."""
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


def _neutralise(text: str) -> str:
    return re.sub(r"<<\s*(END\s+)?EVIDENCE", "‹‹EVIDENCE-TEXT", text, flags=re.IGNORECASE)


def render_evidence(evidence_id: str, tool: str, payload: Any) -> str:
    """Serialise a tool result as a delimited, clearly-untrusted block for the model."""
    body = _neutralise(json.dumps(payload, ensure_ascii=False, default=str))
    return f"{OPEN} id={evidence_id} tool={tool} trust=untrusted>>\n{body}\n{CLOSE} id={evidence_id}>>"
