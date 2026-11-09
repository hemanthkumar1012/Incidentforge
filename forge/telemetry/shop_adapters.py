"""Adapters that reach the shop: config history, config writes, diagnostics, verification.

Each class is constructed with the credentials of exactly one database role:

* ``ShopConfigHistory`` → ``forge_reader`` (SELECT on config_versions/change_events only)
* ``ShopConfigWriter``  → ``forge_remediator`` (INSERT/UPDATE on those two tables only)
"""

from __future__ import annotations

import socket
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from forge.services.ports import VerificationReport
from forge.telemetry.ports import TelemetryUnavailable
from shop.config_admin import rollback_to_version
from shop.db import make_sync_engine
from shop.models import ChangeEvent, ConfigVersion


def _version_row(row: ConfigVersion) -> dict[str, Any]:
    return {
        "version": row.version,
        "payload": dict(row.payload),
        "author": row.author,
        "created_at": row.created_at.isoformat(),
        "active": row.active,
    }


class ShopConfigHistory:
    """Implements both the telemetry ``ChangeHistory`` port and the services ``ConfigReader`` port."""

    def __init__(self, reader_db_url: str) -> None:
        self._sessions = sessionmaker(make_sync_engine(reader_db_url))

    def _query(self, fn: Any) -> Any:
        try:
            with self._sessions() as s:
                return fn(s)
        except SQLAlchemyError as exc:
            raise TelemetryUnavailable(f"change history unavailable: {type(exc).__name__}") from exc

    def recent(self, service: str | None, since: datetime, limit: int) -> list[dict[str, Any]]:
        def run(s: Session) -> list[dict[str, Any]]:
            stmt = select(ChangeEvent).where(ChangeEvent.occurred_at >= since)
            if service:
                stmt = stmt.where(ChangeEvent.service == service)
            rows = s.scalars(stmt.order_by(ChangeEvent.occurred_at.desc()).limit(limit))
            return [
                {
                    "id": e.id,
                    "occurred_at": e.occurred_at.isoformat(),
                    "service": e.service,
                    "kind": e.kind,
                    "summary": e.summary,
                    "actor": e.actor,
                    "from_version": e.from_version,
                    "to_version": e.to_version,
                }
                for e in rows
            ]

        return self._query(run)

    def version(self, service: str, version: int) -> dict[str, Any] | None:
        def run(s: Session) -> dict[str, Any] | None:
            row = s.scalars(
                select(ConfigVersion).where(ConfigVersion.service == service, ConfigVersion.version == version)
            ).one_or_none()
            return _version_row(row) if row else None

        return self._query(run)

    def active(self, service: str) -> dict[str, Any] | None:
        def run(s: Session) -> dict[str, Any] | None:
            row = s.scalars(
                select(ConfigVersion).where(ConfigVersion.service == service, ConfigVersion.active.is_(True))
            ).one_or_none()
            return _version_row(row) if row else None

        return self._query(run)

    def versions(self, service: str, limit: int = 50) -> list[dict[str, Any]]:
        def run(s: Session) -> list[dict[str, Any]]:
            rows = s.scalars(
                select(ConfigVersion)
                .where(ConfigVersion.service == service)
                .order_by(ConfigVersion.version.desc())
                .limit(limit)
            )
            return [_version_row(r) for r in rows]

        return self._query(run)


class ShopConfigWriter:
    def __init__(self, remediator_db_url: str) -> None:
        self._sessions = sessionmaker(make_sync_engine(remediator_db_url))

    def rollback(self, service: str, to_version: int, *, expected_active_version: int, author: str, reason: str) -> int:
        with self._sessions.begin() as s:
            return rollback_to_version(
                s,
                service,
                to_version,
                author=author[:64],
                reason=reason,
                expected_active_version=expected_active_version,
            ).to_version


class HttpDiagnostics:
    """Readiness probes for known services and TCP connects to configured endpoints.

    Only called by the ``run_allowlisted_diagnostic`` tool, which restricts
    targets to the known services and the URLs in checkout's own config.
    """

    def __init__(self, service_urls: dict[str, str], timeout_s: float = 3.0) -> None:
        self._urls = service_urls
        self._timeout = timeout_s

    def readiness(self, service: str) -> dict[str, Any]:
        try:
            resp = httpx.get(self._urls[service] + "/ready", timeout=self._timeout)
        except httpx.HTTPError as exc:
            return {"ready": False, "error": type(exc).__name__}
        return {"ready": resp.status_code == 200, "status_code": resp.status_code}

    def tcp_connect(self, host: str, port: int) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=self._timeout):
                pass
        except OSError as exc:
            return {"reachable": False, "error": exc.strerror or type(exc).__name__}
        return {"reachable": True, "latency_ms": round((time.perf_counter() - start) * 1000, 1)}


def run_journey(base_url: str, card: str = "tok_test_visa", timeout_s: float = 8.0) -> tuple[int, dict[str, Any]]:
    """One synthetic checkout (labelled X-Synthetic) → (status, body)."""
    key = f"forge-verify-{uuid.uuid4().hex[:12]}"
    headers = {"X-Synthetic": "1", "Idempotency-Key": key, "X-Request-ID": key}
    try:
        products = httpx.get(f"{base_url}/api/products", headers=headers, timeout=timeout_s).json()
        sku = next(p["sku"] for p in products.get("products", []) if p.get("stock", 0) > 0)
        resp = httpx.post(
            f"{base_url}/api/checkout",
            headers=headers,
            timeout=timeout_s,
            json={
                "customer_id": "synthetic-forge-verify",
                "card_token": card,
                "items": [{"sku": sku, "qty": 1}],
            },
        )
    except (httpx.HTTPError, StopIteration, ValueError) as exc:
        return 0, {"error": type(exc).__name__}
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {}


class JourneyVerifier:
    """Recovery verification against production: N consecutive successful checkouts."""

    def __init__(self, checkout_url: str, attempts: int = 3, settle_s: float = 5.0) -> None:
        self._url, self._attempts, self._settle = checkout_url, attempts, settle_s

    def verify(self) -> VerificationReport:
        time.sleep(self._settle)  # checkout caches config for a few seconds
        checks = []
        for i in range(self._attempts):
            status, body = run_journey(self._url)
            checks.append(
                {
                    "name": f"checkout_journey_{i + 1}",
                    "passed": status in (200, 201),
                    "status": status,
                    "error_code": (body.get("error") or {}).get("code"),
                }
            )
        return VerificationReport(all(c["passed"] for c in checks), checks)
