"""Isolated validation of a proposed config rollback.

The sandbox is a separate, resettable copy of the shop (own database, own
services; see docs/architecture.md). Validation reproduces the *observed
production state*, never a lab label: it loads the currently active
production config into the sandbox and checks that checkout fails there.

    reset → apply production payload → expect FAILURE (reproduction)
          → apply proposed payload  → expect SUCCESS (recovery)
          → regression checks

Verdicts:

* ``passed``            reproduced, repaired, no regressions
* ``not_reproducible``  sandbox checkout did not fail with the production config, so the
                        repair cannot be shown to fix anything; it is NOT verified
* ``failed``            reproduced, but recovery or regression checks failed
* ``error``             the sandbox itself was unusable (reset or config write failed)

Production URLs are translated by ``to_sandbox_payload`` through an explicit
allowlist (see its docstring). "Copy live configuration" and "sandbox hostnames
only" work together this way: every *value* is copied, but every *host* is
rewritten to a sandbox name or to a name that can never resolve.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

Verdict = Literal["passed", "not_reproducible", "failed", "error"]
RECOVERY_CHECKS = ("checkout_journey",)
REGRESSION_CHECKS = ("declined_card_returns_402", "inventory_ready", "payment_ready")


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


class SandboxPort(Protocol):
    def reset(self) -> None: ...
    def apply_config(self, service: str, payload: dict[str, Any]) -> int: ...
    def run_check(self, name: str) -> CheckResult: ...


@dataclass
class ValidationReport:
    verdict: Verdict
    steps: list[dict[str, Any]] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)


UNRESOLVABLE_HOST = "unresolvable.invalid"  # RFC 6761: .invalid names never resolve


class SandboxMappingRejected(SandboxUnavailable):
    """A production URL cannot be translated safely into the sandbox."""


def to_sandbox_payload(payload: dict[str, Any], host_map: dict[str, str]) -> dict[str, Any]:
    """Translate production service URLs into sandbox URLs using an explicit allowlist.

    * allowlisted hostname → its sandbox name; scheme, port and path are kept, so a
      wrong-port or wrong-path fault is reproduced faithfully;
    * any other hostname → ``unresolvable.invalid``, which reproduces "the caller
      points at a name that does not resolve" without ever being able to reach a
      real host;
    * IP literals and localhost are rejected: they could address something real
      inside the sandbox network (e.g. Postgres), so validation stops with an error.
    """
    out = dict(payload)
    for key, value in payload.items():
        if not (key.endswith("_url") and isinstance(value, str)):
            continue
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if host in ("localhost",) or _is_ip_literal(host):
            raise SandboxMappingRejected(f"{key}: refusing to map address {host!r} into the sandbox")
        sandbox_host = host_map.get(host, UNRESOLVABLE_HOST)
        netloc = sandbox_host + (f":{parts.port}" if parts.port else "")
        out[key] = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return out


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def validate_rollback(
    sandbox: SandboxPort,
    service: str,
    production_payload: dict[str, Any],
    proposed_payload: dict[str, Any],
    host_map: dict[str, str],
) -> ValidationReport:
    report = ValidationReport(
        "error",
        uncertainty=[
            "the sandbox is a copy of the shop, not production: data volume, timing and infrastructure differ",
            "only configuration state is reproduced; faults inside running services are not copied",
        ],
    )

    def record(phase: str, results: list[CheckResult], expect: str) -> None:
        report.steps.append(
            {
                "phase": phase,
                "expect": expect,
                "checks": [{"name": r.name, "passed": r.passed, "detail": r.detail} for r in results],
            }
        )

    try:
        sandbox.reset()
        prod_version = sandbox.apply_config(service, to_sandbox_payload(production_payload, host_map))
        report.steps.append({"phase": "setup", "sandbox_config_version": prod_version})
        repro = [sandbox.run_check("checkout_journey")]
        record("reproduction", repro, "failure")
        if repro[0].passed:
            report.verdict = "not_reproducible"
            report.uncertainty.append(
                "checkout succeeded in the sandbox with the production config; the proposed repair is not verified"
            )
            return report

        sandbox.apply_config(service, to_sandbox_payload(proposed_payload, host_map))
        recovery = [sandbox.run_check(name) for name in RECOVERY_CHECKS]
        record("recovery", recovery, "success")
        regression = [sandbox.run_check(name) for name in REGRESSION_CHECKS]
        record("regression", regression, "success")
    except SandboxUnavailable as exc:
        report.steps.append({"phase": "error", "detail": str(exc)})
        report.verdict = "error"
        return report

    report.verdict = "passed" if all(r.passed for r in recovery + regression) else "failed"
    return report
