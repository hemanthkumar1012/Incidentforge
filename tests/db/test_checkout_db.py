"""Checkout idempotency against real PostgreSQL, with separate connections per request.

Each simulated request uses its own engine (its own connection pool), so the
races below are decided by PostgreSQL's unique index and row locks, not by
anything in-process.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from shop.checkout.orchestrator import (
    Charge,
    CheckoutRequest,
    DependencyError,
    IdempotencyKeyReused,
    LineItem,
    PaymentOutcomeUnknown,
    RequestInProgress,
    Reservation,
    ReservedLine,
    run_checkout,
)
from shop.checkout.repository import SqlOrderRepository
from shop.common.outcomes import Outcome
from shop.db import make_sessionmaker

pytestmark = pytest.mark.db


def repo(url: str) -> tuple[SqlOrderRepository, object]:
    engine = create_async_engine(url, pool_size=1, max_overflow=0)
    return SqlOrderRepository(make_sessionmaker(engine)), engine


class SlowInventory:
    def __init__(self) -> None:
        self.reserved: list[str] = []

    async def reserve(self, order_ref, items):
        await asyncio.sleep(0.2)  # hold the first request in "pending" while the second arrives
        self.reserved.append(order_ref)
        return Reservation("res_" + order_ref[-8:], tuple(ReservedLine(i.sku, i.qty, 1000) for i in items))

    async def release(self, reservation_id): ...
    async def release_for_order(self, order_ref): ...
    async def confirm(self, reservation_id): ...


class Payment:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail, self.charges = fail, 0

    async def charge(self, order_ref, amount_cents, currency, card_token):
        self.charges += 1
        if self.fail:
            raise self.fail
        return Charge("ch_" + order_ref[-8:], "succeeded")


def request(key: str, qty: int = 1) -> CheckoutRequest:
    return CheckoutRequest("cust-db", (LineItem("SKU-1001", qty),), "tok_test_visa", idempotency_key=key)


def test_simultaneous_same_key_one_order_one_charge(databases):
    key = f"db-race-{uuid.uuid4().hex}"
    payment, inventory = Payment(), SlowInventory()

    async def scenario():
        (r1, e1), (r2, e2) = repo(databases["shop"]), repo(databases["shop"])
        try:
            return await asyncio.gather(
                run_checkout(request(key), inventory=inventory, payment=payment, orders=r1, max_items=20),
                run_checkout(request(key), inventory=inventory, payment=payment, orders=r2, max_items=20),
                return_exceptions=True,
            )
        finally:
            await e1.dispose()
            await e2.dispose()

    results = asyncio.run(scenario())
    assert sorted(type(r).__name__ for r in results) == ["CheckoutResult", "RequestInProgress"]
    assert payment.charges == 1 and len(inventory.reserved) == 1

    async def count():
        engine = create_async_engine(databases["shop"])
        async with engine.connect() as conn:
            n = await conn.scalar(text("SELECT count(*) FROM orders WHERE idempotency_key = :k"), {"k": key})
        await engine.dispose()
        return n

    assert asyncio.run(count()) == 1


def test_replay_after_completion_returns_same_order(databases):
    key = f"db-replay-{uuid.uuid4().hex}"
    payment = Payment()

    async def scenario():
        r, e = repo(databases["shop"])
        first = await run_checkout(request(key), inventory=SlowInventory(), payment=payment, orders=r, max_items=20)
        second = await run_checkout(request(key), inventory=SlowInventory(), payment=payment, orders=r, max_items=20)
        await e.dispose()
        return first, second

    first, second = asyncio.run(scenario())
    assert second.replayed and second.order_ref == first.order_ref and payment.charges == 1


def test_same_key_different_payload_rejected(databases):
    key = f"db-reuse-{uuid.uuid4().hex}"

    async def scenario():
        r, e = repo(databases["shop"])
        await run_checkout(request(key, 1), inventory=SlowInventory(), payment=Payment(), orders=r, max_items=20)
        try:
            await run_checkout(request(key, 3), inventory=SlowInventory(), payment=Payment(), orders=r, max_items=20)
        finally:
            await e.dispose()

    with pytest.raises(IdempotencyKeyReused):
        asyncio.run(scenario())


def test_crash_after_claim_then_restart_resumes_same_order(databases):
    """A process dies after claiming; a new process (new engine) resumes once the claim is stale."""
    key = f"db-crash-{uuid.uuid4().hex}"
    order_ref = "ord_" + uuid.uuid4().hex[:16]

    async def scenario():
        r1, e1 = repo(databases["shop"])
        await r1.claim(order_ref, request(key))  # ...and then the process "crashes"
        await e1.dispose()
        r2, e2 = repo(databases["shop"])  # restarted process
        try:
            with pytest.raises(RequestInProgress):  # too fresh: the first attempt might still be running
                await run_checkout(request(key), inventory=SlowInventory(), payment=Payment(), orders=r2, max_items=20)
            async with e2.begin() as conn:
                await conn.execute(
                    text("UPDATE orders SET updated_at = now() - interval '5 minutes' WHERE order_ref = :o"),
                    {"o": order_ref},
                )
            r3, e3 = repo(databases["shop"])
            both = await asyncio.gather(r2.try_resume(order_ref), r3.try_resume(order_ref))
            await e3.dispose()
            assert sorted(both) == [False, True]  # exactly one process takes over
            async with e2.begin() as conn:
                await conn.execute(
                    text("UPDATE orders SET updated_at = now() - interval '5 minutes' WHERE order_ref = :o"),
                    {"o": order_ref},
                )
            return await run_checkout(
                request(key), inventory=SlowInventory(), payment=Payment(), orders=r2, max_items=20
            )
        finally:
            await e2.dispose()

    result = asyncio.run(scenario())
    assert result.order_ref == order_ref and result.status == "confirmed"


def test_uncertain_payment_persists_unknown_and_retry_settles(databases):
    key = f"db-unknown-{uuid.uuid4().hex}"
    payment = Payment(fail=DependencyError("payment", "charge", Outcome.TIMEOUT, "payment:8002"))

    async def scenario():
        r, e = repo(databases["shop"])
        try:
            with pytest.raises(PaymentOutcomeUnknown):
                await run_checkout(request(key), inventory=SlowInventory(), payment=payment, orders=r, max_items=20)
            async with e.connect() as conn:
                status = await conn.scalar(text("SELECT status FROM orders WHERE idempotency_key = :k"), {"k": key})
            payment.fail = None
            settled = await run_checkout(
                request(key), inventory=SlowInventory(), payment=payment, orders=r, max_items=20
            )
            return status, settled
        finally:
            await e.dispose()

    status, settled = asyncio.run(scenario())
    assert status == "unknown" and settled.status == "confirmed"
