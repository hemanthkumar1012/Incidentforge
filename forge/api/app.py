"""FastAPI application for the control plane.

    uvicorn forge.api.app:app

Error contract: every failure is ``{"error": {"code", "message", "details"}}``
with the status from the ``ServiceError`` subclass. Unexpected exceptions are
logged with a traceback and returned as a generic 500 without internals.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from forge.api import routes_incidents, routes_remediation
from forge.api import serializers as ser
from forge.api.deps import Unauthorized, container, current_actor, db
from forge.db.models import AuditEvent
from forge.domain.policy import ROLE_PERMISSIONS, Actor
from forge.identity import AuthError, issue_token
from forge.investigation.tool_catalog import INVESTIGATOR_SCOPES
from forge.services.common import ServiceError
from forge.services.users import authenticate, ensure_bootstrap_users
from forge.settings import ForgeSettings
from forge.telemetry.dashboard import WINDOWS_MINUTES, fetch_dashboard
from forge.telemetry.ports import TelemetryUnavailable
from forge.telemetry.shop_adapters import HttpDiagnostics
from forge.wiring import Container
from shop.common.logging_setup import configure_logging

log = logging.getLogger("forge.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("forge-api", os.environ.get("LOG_LEVEL", "INFO"), os.environ.get("LOKI_PUSH_URL"))
    c = Container(ForgeSettings.from_env())
    with c.sessions.begin() as s:
        created = ensure_bootstrap_users(s, c.settings.bootstrap_users)
    if created:
        log.info("bootstrap users created", extra={"fields": {"users": created}})
    app.state.container = c
    yield


app = FastAPI(title="IncidentForge control plane", version="0.2.0", lifespan=lifespan)
# The web UI is served same-origin through its proxy; CORS is only for explicitly listed dev origins.
CORS_ORIGINS = [o.strip() for o in os.environ.get("FORGE_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(routes_incidents.router)
app.include_router(routes_remediation.router)


@app.exception_handler(ServiceError)
async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "request validation failed",
                "details": {"fields": fields},
            }
        },
    )


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/login", tags=["auth"])
def login(body: Login, session: Session = Depends(db), c: Container = Depends(container)) -> dict[str, Any]:
    try:
        user = authenticate(session, body.username, body.password)
    except AuthError as exc:
        raise Unauthorized(str(exc)) from exc
    return {
        "access_token": issue_token(user.username, user.role, c.settings.jwt_secret),
        "token_type": "bearer",
        "user": {"username": user.username, "role": user.role},
    }


@app.get("/api/me", tags=["auth"])
def me(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return {
        "username": actor.username,
        "role": actor.role,
        "permissions": sorted(p.value for p in ROLE_PERMISSIONS[actor.role]),
    }


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/overview", tags=["system"])
def system_overview(
    actor: Actor = Depends(current_actor), session: Session = Depends(db), c: Container = Depends(container)
) -> dict[str, Any]:
    """Live health of the shop as forge sees it. Every value is queried now; nothing is cached or made up."""
    diag = HttpDiagnostics(c.settings.service_urls)
    services = {name: diag.readiness(name) for name in c.settings.service_urls}
    try:
        active = c.config_history.active("checkout")
        config = {"version": active["version"], "payload": active["payload"]} if active else None
        recent_changes = c.config_history.versions("checkout", limit=10)
    except TelemetryUnavailable as exc:
        config, recent_changes = {"error": str(exc)}, []
    session.execute(text("SELECT 1"))
    return {
        "services": services,
        "topology": {
            "checkout": ["inventory", "payment", "postgres"],
            "inventory": ["postgres"],
            "payment": [],
        },
        "checkout_config": config,
        "config_versions": recent_changes,
        "investigation_default_mode": c.settings.default_mode,
        "llm_configured": bool(c.settings.gemini_api_key),
        "llm_model": c.settings.gemini_model,
        "investigator_scopes": sorted(INVESTIGATOR_SCOPES),
        "viewer": actor.username,
    }


class InvalidWindow(ServiceError):
    status_code, code = 422, "invalid_window"


@app.get("/api/system/timeseries", tags=["system"])
def system_timeseries(
    window: int = 60, _: Actor = Depends(current_actor), c: Container = Depends(container)
) -> dict[str, Any]:
    """Fixed dashboard panels from Prometheus. The client picks only a window from a short allowlist."""
    if window not in WINDOWS_MINUTES:
        raise InvalidWindow(f"window must be one of {list(WINDOWS_MINUTES)} minutes")
    return fetch_dashboard(c.prometheus, window)


@app.get("/api/audit", tags=["audit"])
def audit_log(
    _: Actor = Depends(current_actor),
    session: Session = Depends(db),
    limit: int = 100,
    before_id: int | None = None,
) -> dict[str, Any]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(max(limit, 1), 500))
    if before_id:
        stmt = stmt.where(AuditEvent.id < before_id)
    return {"items": [ser.audit_event(e) for e in session.scalars(stmt)]}


@app.get("/api/evaluations", tags=["evaluation"])
def evaluations(_: Actor = Depends(current_actor)) -> dict[str, Any]:
    """Evaluation results written by `lab evaluate` (read-only mount). Nothing is computed here."""
    directory = Path(os.environ.get("EVAL_RESULTS_DIR", "/app/eval-results"))
    runs = []
    for path in sorted(directory.glob("results-*.json"), reverse=True)[:20]:
        try:
            runs.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            runs.append({"file": path.name, "error": f"unreadable: {type(exc).__name__}"})
    return {"runs": runs, "source": str(directory)}
