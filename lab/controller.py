"""Incident Lab controller: inject, clean up and reset synthetic faults.

The controller depends only on the small ports below; real adapters live in
``lab.adapters``. This keeps the injection/cleanup/reset logic unit-testable
and makes the separation explicit: the lab holds write access to config and
the fault hooks, the investigator holds neither.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lab.scenarios import ConfigPatchInjection, Scenario, ServiceFaultInjection

FAULTABLE_SERVICES = ("inventory", "payment")
RESTORE_ACTOR = "ops"
RESTORE_SUMMARY = "checkout config update"


class LabError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveConfig:
    version: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class InjectionRecord:
    injection_id: int
    scenario_id: str
    details: dict[str, Any] = field(default_factory=dict)


class ConfigPort(Protocol):
    def active(self, service: str) -> ActiveConfig | None: ...
    def apply(
        self,
        service: str,
        payload: dict[str, Any],
        *,
        actor: str,
        reason: str,
        summary: str,
        validate: bool,
    ) -> int: ...


class ServiceAdminPort(Protocol):
    def set_fault(self, service: str, fault: dict[str, Any]) -> None: ...
    def clear_fault(self, service: str) -> None: ...
    def restock(self) -> None: ...


class InjectionStore(Protocol):
    def active(self) -> InjectionRecord | None: ...
    def start(self, scenario: Scenario, details: dict[str, Any]) -> InjectionRecord: ...
    def end(self, injection_id: int, outcome: str) -> None: ...


class LabController:
    def __init__(
        self,
        scenarios: dict[str, Scenario],
        config: ConfigPort,
        admin: ServiceAdminPort,
        store: InjectionStore,
        baselines: dict[str, dict[str, Any]],
    ) -> None:
        self.scenarios = scenarios
        self.config = config
        self.admin = admin
        self.store = store
        self.baselines = baselines

    # ------------------------------------------------------------------ inject
    def inject(self, scenario_id: str) -> InjectionRecord:
        if scenario_id not in self.scenarios:
            raise LabError(f"unknown scenario {scenario_id!r}")
        active = self.store.active()
        if active is not None:
            raise LabError(
                f"injection {active.injection_id} ({active.scenario_id}) is still active; run cleanup or reset first"
            )
        scenario = self.scenarios[scenario_id]
        inj = scenario.injection
        details: dict[str, Any] = {"injection_type": inj.type}
        if isinstance(inj, ConfigPatchInjection):
            current = self.config.active(inj.service)
            if current is None:
                raise LabError(f"{inj.service} has no active config; run the seed first")
            new_payload = {**current.payload, **inj.patch}
            new_version = self.config.apply(
                inj.service,
                new_payload,
                actor=inj.actor,
                reason=inj.reason,
                summary=inj.summary,
                validate=inj.validate_config,
            )
            details.update(service=inj.service, from_version=current.version, to_version=new_version)
        elif isinstance(inj, ServiceFaultInjection):
            self.admin.set_fault(inj.service, inj.fault)
            details.update(service=inj.service, fault=inj.fault)
        else:  # pragma: no cover - guarded by the discriminated union
            raise LabError(f"unsupported injection type {inj!r}")
        return self.store.start(scenario, details)

    # ----------------------------------------------------------------- cleanup
    def cleanup(self) -> dict[str, Any]:
        active = self.store.active()
        if active is None:
            return {"cleaned": None}
        scenario = self.scenarios.get(active.scenario_id)
        if scenario is None:
            raise LabError(f"active injection references unknown scenario {active.scenario_id}")
        actions = self._run_cleanup(scenario)
        self.store.end(active.injection_id, "cleaned_up")
        return {"cleaned": active.scenario_id, "injection_id": active.injection_id, "actions": actions}

    def _run_cleanup(self, scenario: Scenario) -> list[str]:
        c = scenario.cleanup
        if c.type == "restore_baseline_config":
            return [self._restore_baseline(c.service)]
        if c.type == "clear_service_fault":
            self.admin.clear_fault(c.service)
            return [f"cleared {c.service} fault"]
        raise LabError(f"unsupported cleanup {c.type}")  # pragma: no cover

    def _restore_baseline(self, service: str) -> str:
        baseline = self.baselines[service]
        current = self.config.active(service)
        if current is not None and current.payload == baseline:
            return f"{service} config already at baseline (v{current.version})"
        version = self.config.apply(
            service,
            dict(baseline),
            actor=RESTORE_ACTOR,
            reason="restore baseline configuration",
            summary=RESTORE_SUMMARY,
            validate=True,
        )
        return f"{service} config restored to baseline as v{version}"

    # ------------------------------------------------------------------- reset
    def reset(self) -> dict[str, Any]:
        """Return the shop to a known-healthy state, whatever happened before."""
        report: dict[str, Any] = {"cleanup": self.cleanup(), "actions": []}
        for service in FAULTABLE_SERVICES:
            self.admin.clear_fault(service)
            report["actions"].append(f"cleared {service} faults")
        for service in self.baselines:
            report["actions"].append(self._restore_baseline(service))
        self.admin.restock()
        report["actions"].append("restocked inventory to seed levels")
        return report
