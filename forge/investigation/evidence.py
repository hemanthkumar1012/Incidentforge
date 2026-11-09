"""Evidence ledger and claim checking.

Every tool result becomes an evidence item with a short, investigation-local
ID (``E1``, ``E2`` …) that the model cites. Short IDs are easy for the model to
copy correctly, and they map 1:1 to stored rows.

``check_claims`` enforces that a diagnosis only rests on evidence that exists
and succeeded. A hypothesis that cites unknown IDs or only failed queries is an
*unsupported claim* and is rejected before it reaches a human.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from forge.investigation.schemas import Diagnosis
from forge.investigation.toolkit import ToolResult
from forge.investigation.untrusted import detect_injection, render_evidence


@dataclass
class EvidenceItem:
    label: str
    result: ToolResult
    injection_flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.result.ok

    def summary(self) -> str:
        r = self.result
        if not r.ok:
            return f"{r.tool} failed: {(r.error or {}).get('code')}"
        data = r.data or {}
        for key in ("series_count", "count"):
            if key in data:
                return f"{r.tool}: {data[key]} {'series' if key == 'series_count' else 'items'}"
        return f"{r.tool}: ok"

    def render(self) -> str:
        return render_evidence(self.label, self.result.tool, self.result.payload())


class EvidenceLedger:
    def __init__(self, on_add: Callable[[EvidenceItem], None] | None = None) -> None:
        self._items: dict[str, EvidenceItem] = {}
        self._on_add = on_add

    def add(self, result: ToolResult) -> EvidenceItem:
        label = f"E{len(self._items) + 1}"
        flags = detect_injection(str(result.payload()))
        item = EvidenceItem(label, result, flags)
        self._items[label] = item
        if self._on_add:
            self._on_add(item)
        return item

    def get(self, label: str) -> EvidenceItem | None:
        return self._items.get(label)

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> list[EvidenceItem]:
        return list(self._items.values())


def check_claims(diagnosis: Diagnosis, ledger: EvidenceLedger) -> list[str]:
    """Problems that make ``diagnosis`` unsupported by the collected evidence."""
    problems: list[str] = []
    if diagnosis.outcome == "diagnosed" and not any(i.ok for i in ledger.items()):
        problems.append("a diagnosis requires at least one successful tool result")
    for h in diagnosis.hypotheses:
        cited = [*h.evidence_ids, *h.contradicting_evidence_ids]
        unknown = [e for e in cited if ledger.get(e) is None]
        if unknown:
            problems.append(f"hypothesis {h.rank} cites unknown evidence {unknown}")
            continue
        supporting_ok = [e for e in h.evidence_ids if ledger.get(e).ok]  # type: ignore[union-attr]
        if not supporting_ok:
            problems.append(f"hypothesis {h.rank} cites only failed tool results")
        if h.confidence == "high" and len(supporting_ok) < 2:
            problems.append(f"hypothesis {h.rank} claims high confidence with fewer than 2 supporting items")
    return problems


def evidence_index(ledger: EvidenceLedger) -> list[dict[str, Any]]:
    return [{"id": i.label, "tool": i.result.tool, "ok": i.ok, "summary": i.summary()} for i in ledger.items()]
