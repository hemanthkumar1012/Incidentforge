"""Shared FastAPI service scaffolding: settings, telemetry, DB, errors, admin auth."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from shop.common.context import request_id_var
from shop.common.logging_setup import configure_logging
from shop.common.settings import ServiceSettings
from shop.common.telemetry import install_http_middleware, setup_tracing
from shop.db import make_async_engine, make_sessionmaker


@dataclass
class ServiceRuntime:
    settings: ServiceSettings
    engine: AsyncEngine | None
    sessionmaker: async_sessionmaker | None

    @property
    def sessions(self) -> async_sessionmaker:
        if self.sessionmaker is None:
            raise RuntimeError(f"{self.settings.service_name} was bootstrapped without a database")
        return self.sessionmaker

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def bootstrap(app: FastAPI, service_name: str, *, use_db: bool = True) -> ServiceRuntime:
    """Configure logging/tracing/metrics and create the DB engine.

    Called at import time of each service module so middleware is installed
    before the app starts.
    """
    settings = ServiceSettings.from_env(service_name)
    configure_logging(service_name, settings.log_level, settings.loki_push_url)
    setup_tracing(service_name, settings.otlp_traces_endpoint)
    install_http_middleware(app, service_name)
    engine: AsyncEngine | None = None
    if use_db:
        if not settings.database_url:
            raise RuntimeError("SHOP_DATABASE_URL is required for " + service_name)
        engine = make_async_engine(settings.database_url)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    @app.exception_handler(HTTPException)
    async def _http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response(exc.status_code, "http_error", str(exc.detail))

    return ServiceRuntime(settings, engine, make_sessionmaker(engine) if engine else None)


def error_response(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message, "request_id": request_id_var.get()}
    body.update(extra)
    return JSONResponse(status_code=status, content={"error": body})


async def db_ready(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        return False


def require_lab_token(request: Request, settings: ServiceSettings) -> None:
    """Gate for fault-injection admin endpoints.

    Disabled (404) when LAB_ADMIN_TOKEN is unset; 403 on a wrong token. Uses a
    constant-time comparison.
    """
    expected = settings.lab_admin_token
    if not expected:
        raise HTTPException(status_code=404, detail="not found")
    supplied = request.headers.get("X-Lab-Token", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="forbidden")
