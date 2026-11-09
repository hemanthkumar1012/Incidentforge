"""Payment simulator. No real payment processing of any kind.

* ``tok_test_*`` tokens are accepted; ``tok_test_decline`` is always declined.
* ``Idempotency-Key`` makes retries safe: a repeated key returns the original
  result. Results are kept in a bounded in-memory LRU (simulator scope).
* Lab hooks can add latency or a seeded error rate.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shop.common.faults import FaultConfig, FaultInjector
from shop.common.service import bootstrap, error_response, require_lab_token

log = logging.getLogger("shop.payment")
MAX_REMEMBERED = 10_000


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("payment simulator started")
    try:
        yield
    finally:
        await runtime.dispose()


app = FastAPI(title="Payment Simulator", version="1.0.0", lifespan=lifespan)
runtime = bootstrap(app, "payment", use_db=False)
faults = FaultInjector()
_results: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
_results_lock = asyncio.Lock()


class ChargeIn(BaseModel):
    order_ref: str = Field(min_length=1, max_length=40)
    amount_cents: int = Field(gt=0, le=10_000_000)
    currency: str = Field(pattern=r"^(USD|INR|EUR)$")
    card_token: str = Field(min_length=4, max_length=64)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "payment"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    # The simulator has no hard dependencies; ready == alive.
    return {"status": "ready"}


def _decide(body: ChargeIn) -> tuple[int, dict[str, Any]]:
    if not body.card_token.startswith("tok_test_"):
        return 422, {"error": {"code": "invalid_token", "message": "only tok_test_* tokens are accepted"}}
    if body.card_token == "tok_test_decline":  # noqa: S105 - public test token
        return 402, {"error": {"code": "card_declined", "message": "card declined (simulated)"}}
    return 201, {
        "charge_id": "ch_" + uuid.uuid4().hex[:16],
        "status": "succeeded",
        "amount_cents": body.amount_cents,
        "currency": body.currency,
        "simulated": True,
    }


@app.post("/api/charges", status_code=201)
async def charge(body: ChargeIn, idempotency_key: str | None = Header(default=None, max_length=80)) -> JSONResponse:
    decision = faults.decide()
    if decision.delay_s:
        await asyncio.sleep(decision.delay_s)
    if decision.error_status:
        # Injected errors happen before the idempotency record, so a retry may succeed.
        log.error(
            "charge processing error",
            extra={"fields": {"order_ref": body.order_ref, "status": decision.error_status}},
        )
        return error_response(decision.error_status, "processor_error", "payment processor error")

    async with _results_lock:
        if idempotency_key and idempotency_key in _results:
            status, payload = _results[idempotency_key]
            _results.move_to_end(idempotency_key)
            return JSONResponse(status_code=status, content={**payload, "replayed": True})
        status, payload = _decide(body)
        if idempotency_key:
            _results[idempotency_key] = (status, payload)
            while len(_results) > MAX_REMEMBERED:
                _results.popitem(last=False)
    log.info(
        "charge processed",
        extra={"fields": {"order_ref": body.order_ref, "status": status, "amount_cents": body.amount_cents}},
    )
    return JSONResponse(status_code=status, content=payload)


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
