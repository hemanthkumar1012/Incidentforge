"""Exact-action approval binding.

An approval is valid for one precise action, never "the proposal" in general.
The binding digest covers everything that determines what will change in
production:

* action type and exact target,
* the full parameter set,
* the production config version the action expects to replace,
* the validation run whose results the approver looked at.

If any of these differ when execution is requested, the digests differ and
the approval does not apply. The digest is SHA-256 over canonical JSON
(sorted keys, no whitespace), so it is stable across processes and Python
versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ActionBinding:
    action_type: str
    target: str
    parameters: dict[str, Any]
    expected_active_version: int
    validation_run_id: str

    def digest(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
