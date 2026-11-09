"""Checkout service: storefront, product listing proxy, checkout, order lookup."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from shop.checkout.clients import HttpInventoryClient, HttpPaymentClient
from shop.checkout.orchestrator import (
    CheckoutError,
    CheckoutRequest,
    DependencyError,
    LineItem,
    run_checkout,
)
from shop.checkout.repository import SqlOrderRepository
from shop.common.context import synthetic_var
from shop.common.service import bootstrap, db_ready, error_response
from shop.common.telemetry import CHECKOUT_ORDERS, outbound_headers
from shop.runtime_config import CheckoutConfigStore, ConfigUnavailable

log = logging.getLogger("shop.checkout")
STATIC_DIR = Path(__file__).parent / "static"
# Errors after which the client should retry with the SAME Idempotency-Key (docs/checkout-contract.md).
RETRY_SAME_KEY = frozenset({"request_in_progress", "payment_outcome_unknown"})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    app.state.http = httpx.AsyncClient(limits=limits)
    log.info("checkout started")
    try:
        yield
    finally:
        await app.state.http.aclose()
        await runtime.dispose()


app = FastAPI(title="Shop Checkout", version="1.0.0", lifespan=lifespan)
runtime = bootstrap(app, "checkout")
config_store = CheckoutConfigStore(runtime.sessions, observer="checkout", ttl_s=runtime.settings.config_cache_ttl_s)
orders = SqlOrderRepository(runtime.sessions)


class LineItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    qty: int = Field(ge=1, le=50)


class CheckoutIn(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    items: list[LineItemIn] = Field(min_length=1, max_length=100)
    card_token: str = Field(min_length=4, max_length=64)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "checkout"}


@app.get("/ready")
async def ready() -> JSONResponse:
    checks = {"database": await db_ready(runtime.engine)}
    try:
        loaded = await config_store.get()
        checks["config"] = True
        version: int | None = loaded.version
    except ConfigUnavailable:
        checks["config"] = False
        version = None
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks, "config_version": version},
    )


@app.get("/", include_in_schema=False)
async def storefront() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/products")
async def products() -> JSONResponse:
    try:
        cfg = (await config_store.get()).config
    except ConfigUnavailable as exc:
        return error_response(503, "config_unavailable", str(exc))
    try:
        resp = await app.state.http.get(
            cfg.inventory_url + "/api/products",
            timeout=cfg.inventory_timeout_s,
            headers=outbound_headers(),
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("product listing failed", extra={"fields": {"error": type(exc).__name__}})
        return error_response(502, "inventory_unavailable", "product catalogue unavailable")
    return JSONResponse(resp.json())


@app.post("/api/checkout", status_code=201)
async def checkout(body: CheckoutIn, idempotency_key: str | None = Header(default=None, max_length=80)) -> JSONResponse:
    try:
        loaded = await config_store.get()
    except ConfigUnavailable as exc:
        CHECKOUT_ORDERS.labels("failed", "config_unavailable").inc()
        return error_response(503, "config_unavailable", str(exc))
    cfg = loaded.config
    http = app.state.http
    request = CheckoutRequest(
        customer_id=body.customer_id,
        items=tuple(LineItem(i.sku, i.qty) for i in body.items),
        card_token=body.card_token,
        currency=cfg.currency,
        idempotency_key=idempotency_key,
        synthetic=synthetic_var.get(),
    )
    try:
        result = await run_checkout(
            request,
            inventory=HttpInventoryClient(http, cfg.inventory_url, cfg.inventory_timeout_s),
            payment=HttpPaymentClient(http, cfg.payment_url, cfg.payment_timeout_s),
            orders=orders,
            max_items=cfg.max_items_per_order,
        )
    except DependencyError as exc:
        CHECKOUT_ORDERS.labels("failed", f"{exc.dependency}_unavailable").inc()
        log.error(
            "checkout failed",
            extra={
                "fields": {
                    "reason": f"{exc.dependency}_unavailable",
                    "dependency": exc.dependency,
                    "operation": exc.operation,
                    "outcome": exc.outcome.value,
                    "target": exc.target,
                    "config_version": loaded.version,
                }
            },
        )
        return error_response(exc.http_status, exc.code, f"{exc.dependency} unavailable", dependency=exc.dependency)
    except CheckoutError as exc:
        CHECKOUT_ORDERS.labels("failed", exc.code).inc()
        log.info("checkout rejected", extra={"fields": {"reason": exc.code}})
        response = error_response(exc.http_status, exc.code, str(exc))
        if exc.code in RETRY_SAME_KEY:
            response.headers["Retry-After"] = "2"
        return response

    CHECKOUT_ORDERS.labels("confirmed", "none").inc()
    log.info(
        "checkout confirmed",
        extra={
            "fields": {
                "order_ref": result.order_ref,
                "total_cents": result.total_cents,
                "replayed": result.replayed,
                "config_version": loaded.version,
            }
        },
    )
    return JSONResponse(
        status_code=200 if result.replayed else 201,
        content={
            "order_ref": result.order_ref,
            "status": result.status,
            "total_cents": result.total_cents,
            "currency": cfg.currency,
            "charge_id": result.charge_id,
            "replayed": result.replayed,
        },
    )


@app.get("/api/orders/{order_ref}")
async def get_order(order_ref: str) -> JSONResponse:
    if not order_ref.startswith("ord_") or len(order_ref) > 40:
        return error_response(404, "not_found", "order not found")
    order = await orders.get(order_ref)
    if order is None:
        return error_response(404, "not_found", "order not found")
    return JSONResponse(
        {
            "order_ref": order.order_ref,
            "status": order.status,
            "failure_reason": order.failure_reason,
            "total_cents": order.total_cents,
            "currency": order.currency,
            "items": [{"sku": i.sku, "qty": i.qty, "unit_price_cents": i.unit_price_cents} for i in order.items],
            "created_at": order.created_at.isoformat(),
        }
    )
