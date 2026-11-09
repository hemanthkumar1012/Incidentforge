"""Sandbox adapter: the separate, resettable copy of the shop used for validation.

The sandbox has its own database (``shop_validation``, role ``sandbox_app``)
and its own checkout/inventory/payment containers. Forge holds sandbox
credentials only. Nothing here can reach the production shop database.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from forge.telemetry.shop_adapters import run_journey
from forge.validation.runner import CheckResult, SandboxUnavailable
from shop.config_admin import apply_config
from shop.db import make_sync_engine
from shop.seed import SANDBOX_CHECKOUT_CONFIG

SANDBOX_HOSTS = {"payment": "sandbox-payment", "inventory": "sandbox-inventory"}


class ShopSandbox:
    def __init__(self, db_url: str, service_urls: dict[str, str], admin_token: str) -> None:
        self._sessions = sessionmaker(make_sync_engine(db_url))
        self._urls = service_urls
        self._headers = {"X-Lab-Token": admin_token}

    def _admin(self, method: str, service: str, path: str) -> None:
        try:
            resp = httpx.request(method, self._urls[service] + path, headers=self._headers, timeout=5)
        except httpx.HTTPError as exc:
            raise SandboxUnavailable(f"sandbox {service} unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 300:
            raise SandboxUnavailable(f"sandbox {service} admin call returned {resp.status_code}")

    def reset(self) -> None:
        for service in ("payment", "inventory"):
            self._admin("DELETE", service, "/admin/faults")
        self._admin("POST", "inventory", "/admin/restock")
        self.apply_config("checkout", dict(SANDBOX_CHECKOUT_CONFIG))

    def apply_config(self, service: str, payload: dict[str, Any]) -> int:
        try:
            with self._sessions.begin() as s:
                # validate=False: reproducing an invalid production config is legitimate here.
                return apply_config(
                    s,
                    service,
                    payload,
                    author="forge-validator",
                    reason="validation run",
                    summary="sandbox config for validation",
                    validate=False,
                ).to_version
        except SQLAlchemyError as exc:
            raise SandboxUnavailable(f"sandbox database unavailable: {type(exc).__name__}") from exc

    def run_check(self, name: str) -> CheckResult:
        checkout = self._urls["checkout"]
        if name == "checkout_journey":
            status, body = run_journey(checkout)
            return CheckResult(
                name, status in (200, 201), f"status {status} {(body.get('error') or {}).get('code', '')}"
            )
        if name == "declined_card_returns_402":
            status, _ = run_journey(checkout, card="tok_test_decline")
            return CheckResult(name, status == 402, f"status {status}")
        if name in ("inventory_ready", "payment_ready"):
            service = name.removesuffix("_ready")
            try:
                ok = httpx.get(self._urls[service] + "/ready", timeout=3).status_code == 200
            except httpx.HTTPError:
                ok = False
            return CheckResult(name, ok)
        raise ValueError(f"unknown validation check {name!r}")
