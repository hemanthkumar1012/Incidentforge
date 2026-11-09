"""Incident Lab CLI.

    python -m lab list
    python -m lab inject S1
    python -m lab status
    python -m lab cleanup
    python -m lab reset            # reset-to-healthy, then verify health

Requires LAB_SHOP_DATABASE_URL, LAB_DATABASE_URL, LAB_ADMIN_TOKEN and the
service URLs (defaults match docker-compose).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

from lab.controller import LabController, LabError
from lab.scenarios import load_all
from shop.seed import BASELINE_CHECKOUT_CONFIG


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        print(f"error: {name} is not set", file=sys.stderr)
        raise SystemExit(2)
    return value


def service_urls() -> dict[str, str]:
    return {
        "checkout": _env("CHECKOUT_URL", "http://checkout:8000"),
        "inventory": _env("INVENTORY_URL", "http://inventory:8001"),
        "payment": _env("PAYMENT_URL", "http://payment:8002"),
    }


def build_controller() -> tuple[LabController, object]:
    from lab.adapters import ServiceAdminAdapter, ShopConfigAdapter, SqlInjectionStore

    store = SqlInjectionStore(_env("LAB_DATABASE_URL"))
    controller = LabController(
        scenarios=load_all(),
        config=ShopConfigAdapter(_env("LAB_SHOP_DATABASE_URL")),
        admin=ServiceAdminAdapter(service_urls(), _env("LAB_ADMIN_TOKEN")),
        store=store,
        baselines={"checkout": BASELINE_CHECKOUT_CONFIG},
    )
    return controller, store


def wait_healthy(timeout_s: float = 30.0) -> dict[str, bool]:
    """Poll /ready on every service until all are ready or the timeout passes."""
    deadline = time.monotonic() + timeout_s
    status: dict[str, bool] = {}
    while True:
        for name, url in service_urls().items():
            try:
                status[name] = httpx.get(url + "/ready", timeout=3).status_code == 200
            except httpx.HTTPError:
                status[name] = False
        if all(status.values()) or time.monotonic() > deadline:
            return status
        time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab", description="IncidentForge Incident Lab (synthetic faults)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_inj = sub.add_parser("inject")
    p_inj.add_argument("scenario_id")
    sub.add_parser("status")
    sub.add_parser("cleanup")
    sub.add_parser("reset")
    p_eval = sub.add_parser("evaluate", help="run the evaluation (needs EVAL_OPERATOR/EVAL_APPROVER=user:password)")
    p_eval.add_argument("--modes", default="runbook", help="comma list: runbook,llm_summary,llm")
    p_eval.add_argument("--trials", type=int, default=3)
    p_eval.add_argument("--scenarios", default="", help="comma list of scenario ids (default: all)")
    p_eval.add_argument("--no-recover", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for sc in load_all().values():
            print(f"{sc.id}\t{sc.split}\t{sc.title}")
        return 0

    controller, store = build_controller()
    try:
        if args.cmd == "inject":
            rec = controller.inject(args.scenario_id)
            print(
                json.dumps(
                    {
                        "injected": rec.scenario_id,
                        "injection_id": rec.injection_id,
                        "details": rec.details,
                        "label": "SYNTHETIC INJECTED INCIDENT",
                    }
                )
            )
        elif args.cmd == "status":
            rows = store.recent(10)  # type: ignore[attr-defined]
            for r in rows:
                state = "ACTIVE" if r.ended_at is None else f"ended ({r.outcome})"
                print(f"#{r.id}\t{r.scenario_id}\t{r.started_at:%Y-%m-%d %H:%M:%S}\t{state}")
            if not rows:
                print("no injections recorded")
        elif args.cmd == "cleanup":
            print(json.dumps(controller.cleanup()))
        elif args.cmd == "evaluate":
            from lab import evaluate

            return evaluate.main(
                controller,
                args.modes.split(","),
                args.trials,
                [x for x in args.scenarios.split(",") if x],
                recover=not args.no_recover,
            )
        elif args.cmd == "reset":
            report = controller.reset()
            health = wait_healthy()
            report["health"] = health
            print(json.dumps(report, indent=2))
            if not all(health.values()):
                print("reset completed but not all services are ready", file=sys.stderr)
                return 1
    except LabError as exc:
        print(f"lab error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
