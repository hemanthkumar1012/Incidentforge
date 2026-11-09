"""Inventory service: catalogue, stock reservations, and lab fault hooks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from shop.common.faults import FaultConfig, FaultInjector
from shop.common.service import bootstrap, db_ready, error_response, require_lab_token
from shop.models import Product, Reservation, ReservationItem

log = logging.getLogger("shop.inventory")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("inventory started")
    try:
        yield
    finally:
        await runtime.dispose()


app = FastAPI(title="Shop Inventory", version="1.0.0", lifespan=lifespan)
runtime = bootstrap(app, "inventory")
faults = FaultInjector()


async def _apply_faults() -> JSONResponse | None:
    """Lab hook: simulated slow dependency (e.g. a slow storage backend)."""
    decision = faults.decide()
    if decision.delay_s:
        await asyncio.sleep(decision.delay_s)
    if decision.error_status:
        return error_response(decision.error_status, "inventory_error", "inventory backend error")
    return None


class ReserveItem(BaseModel):
    sku: str = Field(min_length=1, max_length=32)
    qty: int = Field(ge=1, le=50)


class ReserveIn(BaseModel):
    order_ref: str = Field(min_length=1, max_length=40)
    items: list[ReserveItem] = Field(min_length=1, max_length=100)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "inventory"}


@app.get("/ready")
async def ready() -> JSONResponse:
    ok = await db_ready(runtime.engine)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": {"database": ok}},
    )


@app.get("/api/products")
async def list_products() -> JSONResponse:
    if (err := await _apply_faults()) is not None:
        return err
    async with runtime.sessions() as s:
        rows = (await s.scalars(select(Product).order_by(Product.sku))).all()
    return JSONResponse(
        {
            "products": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "price_cents": p.price_cents,
                    "currency": p.currency,
                    "stock": p.stock,
                }
                for p in rows
            ]
        }
    )


@app.post("/api/reservations", status_code=201)
async def reserve(body: ReserveIn) -> JSONResponse:
    if (err := await _apply_faults()) is not None:
        return err
    wanted = {i.sku: i.qty for i in body.items}
    if len(wanted) != len(body.items):
        return error_response(422, "invalid_order", "duplicate SKU")
    existing = await _find_reservation(body.order_ref)
    if existing is not None:
        return _replay_reservation(existing, wanted)
    try:
        return await _create_reservation(body.order_ref, wanted)
    except IntegrityError:
        # A concurrent request for the same order won the unique index on
        # order_ref; our transaction (including its stock decrement) rolled back.
        existing = await _find_reservation(body.order_ref)
        if existing is None:
            raise
        return _replay_reservation(existing, wanted)


async def _find_reservation(order_ref: str) -> Reservation | None:
    async with runtime.sessions() as s:
        return (await s.scalars(select(Reservation).where(Reservation.order_ref == order_ref))).one_or_none()


def _replay_reservation(res: Reservation, wanted: dict[str, int]) -> JSONResponse:
    held = {i.sku: i.qty for i in res.items}
    if held != wanted:
        return error_response(409, "order_ref_conflict", "order already has a different reservation")
    lines = [
        {"sku": i.sku, "qty": i.qty, "unit_price_cents": i.unit_price_cents}
        for i in sorted(res.items, key=lambda i: i.sku)
    ]
    return JSONResponse(
        status_code=200,
        content={"reservation_id": res.id, "lines": lines, "status": res.status, "replayed": True},
    )


async def _create_reservation(order_ref: str, wanted: dict[str, int]) -> JSONResponse:
    reservation_id = "res_" + uuid.uuid4().hex[:16]
    async with runtime.sessions() as s, s.begin():
        # Lock rows in a fixed order (by SKU) so concurrent reservations cannot deadlock.
        products = (
            await s.scalars(
                select(Product).where(Product.sku.in_(sorted(wanted))).order_by(Product.sku).with_for_update()
            )
        ).all()
        found = {p.sku: p for p in products}
        missing = sorted(set(wanted) - set(found))
        if missing:
            return error_response(422, "unknown_sku", f"unknown SKU(s): {', '.join(missing)}")
        short = [sku for sku, qty in wanted.items() if found[sku].stock < qty]
        if short:
            return error_response(409, "out_of_stock", f"insufficient stock for {', '.join(sorted(short))}")
        s.add(Reservation(id=reservation_id, order_ref=order_ref, status="held"))
        await s.flush()
        lines = []
        for sku, qty in sorted(wanted.items()):
            p = found[sku]
            p.stock -= qty
            s.add(ReservationItem(reservation_id=reservation_id, sku=sku, qty=qty, unit_price_cents=p.price_cents))
            lines.append({"sku": sku, "qty": qty, "unit_price_cents": p.price_cents})
    log.info(
        "stock reserved",
        extra={"fields": {"reservation_id": reservation_id, "order_ref": order_ref, "lines": len(lines)}},
    )
    return JSONResponse(status_code=201, content={"reservation_id": reservation_id, "lines": lines})


async def _transition(reservation_id: str, to_status: str) -> JSONResponse:
    async with runtime.sessions() as s, s.begin():
        res = (
            await s.scalars(select(Reservation).where(Reservation.id == reservation_id).with_for_update())
        ).one_or_none()
        if res is None:
            return error_response(404, "not_found", "reservation not found")
        if res.status == to_status:  # idempotent
            return JSONResponse({"reservation_id": reservation_id, "status": res.status})
        if res.status != "held":
            return error_response(409, "invalid_transition", f"reservation is {res.status}")
        if to_status == "released":
            for item in res.items:
                await s.execute(update(Product).where(Product.sku == item.sku).values(stock=Product.stock + item.qty))
        res.status = to_status
    log.info("reservation updated", extra={"fields": {"reservation_id": reservation_id, "status": to_status}})
    return JSONResponse({"reservation_id": reservation_id, "status": to_status})


@app.post("/api/reservations/{reservation_id}/release")
async def release(reservation_id: str) -> JSONResponse:
    return await _transition(reservation_id, "released")


@app.post("/api/orders/{order_ref}/reservation/release")
async def release_for_order(order_ref: str) -> JSONResponse:
    res = await _find_reservation(order_ref)
    if res is None:
        return error_response(404, "not_found", "no reservation for this order")
    return await _transition(res.id, "released")


@app.post("/api/reservations/{reservation_id}/confirm")
async def confirm(reservation_id: str) -> JSONResponse:
    return await _transition(reservation_id, "committed")


# ---------------------------------------------------------------- lab admin
@app.put("/admin/faults", include_in_schema=False)
async def set_faults(cfg: FaultConfig, request: Request) -> dict[str, object]:
    require_lab_token(request, runtime.settings)
    faults.set(cfg)
    return {"active": cfg.active}


@app.delete("/admin/faults", include_in_schema=False)
async def clear_faults(request: Request) -> dict[str, object]:
    require_lab_token(request, runtime.settings)
    faults.clear()
    return {"active": False}


@app.post("/admin/restock", include_in_schema=False)
async def restock(request: Request) -> dict[str, object]:
    require_lab_token(request, runtime.settings)
    async with runtime.sessions() as s, s.begin():
        result = await s.execute(update(Product).values(stock=Product.seed_stock))
    return {"restocked": result.rowcount}
