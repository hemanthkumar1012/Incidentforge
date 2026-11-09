"""Real adapters for the lab controller: Postgres (shop + lab DBs) and service admin APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from lab.controller import ActiveConfig, InjectionRecord, LabError
from lab.scenarios import Scenario
from shop.config_admin import apply_config, get_active
from shop.db import make_sync_engine


# ------------------------------------------------------------- shop config
class ShopConfigAdapter:
    def __init__(self, shop_db_url: str) -> None:
        self._sm = sessionmaker(make_sync_engine(shop_db_url))

    def active(self, service: str) -> ActiveConfig | None:
        with self._sm() as s:
            row = get_active(s, service)
            return ActiveConfig(row.version, dict(row.payload)) if row else None

    def apply(
        self, service: str, payload: dict[str, Any], *, actor: str, reason: str, summary: str, validate: bool
    ) -> int:
        with self._sm() as s, s.begin():
            result = apply_config(s, service, payload, author=actor, reason=reason, summary=summary, validate=validate)
        return result.to_version


# ----------------------------------------------------------- service admin
class ServiceAdminAdapter:
    def __init__(self, base_urls: dict[str, str], token: str, timeout_s: float = 5.0) -> None:
        self._urls = base_urls
        self._headers = {"X-Lab-Token": token}
        self._timeout = timeout_s

    def _req(self, method: str, service: str, path: str, json: Any = None) -> None:
        url = self._urls[service] + path
        try:
            resp = httpx.request(method, url, json=json, headers=self._headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise LabError(f"{service} admin call failed: {type(exc).__name__}") from exc
        if resp.status_code >= 300:
            raise LabError(f"{service} admin call returned {resp.status_code}: {resp.text[:200]}")

    def set_fault(self, service: str, fault: dict[str, Any]) -> None:
        self._req("PUT", service, "/admin/faults", json=fault)

    def clear_fault(self, service: str) -> None:
        self._req("DELETE", service, "/admin/faults")

    def restock(self) -> None:
        self._req("POST", "inventory", "/admin/restock")


# --------------------------------------------------------- injection store
class LabBase(DeclarativeBase):
    pass


class InjectionRow(LabBase):
    """Lab-private record of injections, including the ground-truth snapshot.

    Lives in the separate ``lab`` database, reachable only with lab credentials.
    """

    __tablename__ = "injections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))
    ground_truth: Mapped[dict[str, Any]] = mapped_column(JSON)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)


class SqlInjectionStore:
    def __init__(self, lab_db_url: str) -> None:
        engine = make_sync_engine(lab_db_url)
        # The lab schema is one small private table; create_all keeps the lab
        # self-contained instead of adding a second Alembic environment.
        LabBase.metadata.create_all(engine)
        self._sm = sessionmaker(engine)

    def active(self) -> InjectionRecord | None:
        with self._sm() as s:
            row = s.scalars(
                select(InjectionRow).where(InjectionRow.ended_at.is_(None)).order_by(InjectionRow.id.desc())
            ).first()
            return InjectionRecord(row.id, row.scenario_id, dict(row.details)) if row else None

    def start(self, scenario: Scenario, details: dict[str, Any]) -> InjectionRecord:
        with self._sm() as s, s.begin():
            row = InjectionRow(
                scenario_id=scenario.id,
                started_at=datetime.now(UTC),
                ground_truth=scenario.ground_truth.model_dump(),
                details=details,
            )
            s.add(row)
            s.flush()
            return InjectionRecord(row.id, row.scenario_id, details)

    def end(self, injection_id: int, outcome: str) -> None:
        with self._sm() as s, s.begin():
            row = s.get(InjectionRow, injection_id)
            if row is not None and row.ended_at is None:
                row.ended_at = datetime.now(UTC)
                row.outcome = outcome

    def recent(self, limit: int = 20) -> list[InjectionRow]:
        with self._sm() as s:
            return list(s.scalars(select(InjectionRow).order_by(InjectionRow.id.desc()).limit(limit)))
