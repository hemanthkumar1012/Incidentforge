"""SQLAlchemy implementation of the checkout OrderRepository protocol."""

from __future__ import annotations

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from shop.checkout.orchestrator import (
    RESUME_AFTER_SECONDS,
    Charge,
    CheckoutRequest,
    ExistingOrder,
    OrderClaim,
    Reservation,
)
from shop.models import Order, OrderItem


class SqlOrderRepository:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def claim(self, order_ref: str, request: CheckoutRequest) -> OrderClaim:
        """Atomically create the pending order or find the one holding the key.

        ``ON CONFLICT DO NOTHING`` makes the insert and the uniqueness check a
        single statement: of two concurrent requests with the same key exactly one
        inserts; the other gets no row back and reads the winner. (Without a key
        there is nothing to conflict on and the insert always succeeds.)
        """
        async with self._sm() as s, s.begin():
            inserted = await s.scalar(
                insert(Order)
                .values(
                    order_ref=order_ref,
                    customer_id=request.customer_id,
                    status="pending",
                    currency=request.currency,
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request.fingerprint(),
                    synthetic=request.synthetic,
                )
                .on_conflict_do_nothing(index_elements=[Order.idempotency_key])
                .returning(Order.order_ref)
            )
            if inserted is not None:
                for item in request.items:
                    s.add(OrderItem(order_ref=order_ref, sku=item.sku, qty=item.qty))
                return OrderClaim(created=True)
            row = (await s.scalars(select(Order).where(Order.idempotency_key == request.idempotency_key))).one()
            stale = bool(await s.scalar(select(row.updated_at < func.now() - _resume_interval())))
            return OrderClaim(
                created=False,
                existing=ExistingOrder(
                    row.order_ref,
                    row.status,
                    row.total_cents,
                    row.charge_id,
                    row.failure_reason,
                    row.request_fingerprint,
                    stale,
                ),
            )

    async def try_resume(self, order_ref: str) -> bool:
        # The status/age condition in the UPDATE makes takeover atomic: of two
        # concurrent retries, only one sees its row returned.
        async with self._sm() as s, s.begin():
            taken = await s.scalar(
                update(Order)
                .where(
                    Order.order_ref == order_ref,
                    or_(
                        Order.status == "unknown",
                        (Order.status == "pending") & (Order.updated_at < func.now() - _resume_interval()),
                    ),
                )
                .values(status="pending", updated_at=func.now())
                .returning(Order.order_ref)
            )
            return taken is not None

    async def mark_unknown(self, order_ref: str, total_cents: int, reservation_id: str) -> None:
        async with self._sm() as s, s.begin():
            await s.execute(
                update(Order)
                .where(Order.order_ref == order_ref)
                .values(
                    status="unknown",
                    failure_reason="payment_outcome_unknown",
                    total_cents=total_cents,
                    reservation_id=reservation_id,
                )
            )

    async def mark_confirmed(self, order_ref: str, reservation: Reservation, charge: Charge) -> None:
        prices = {line.sku: line.unit_price_cents for line in reservation.lines}
        async with self._sm() as s, s.begin():
            await s.execute(
                update(Order)
                .where(Order.order_ref == order_ref)
                .values(
                    status="confirmed",
                    total_cents=reservation.total_cents,
                    reservation_id=reservation.reservation_id,
                    charge_id=charge.charge_id,
                )
            )
            for sku, price in prices.items():
                await s.execute(
                    update(OrderItem)
                    .where(OrderItem.order_ref == order_ref, OrderItem.sku == sku)
                    .values(unit_price_cents=price)
                )

    async def mark_failed(self, order_ref: str, reason: str, total_cents: int | None) -> None:
        async with self._sm() as s, s.begin():
            await s.execute(
                update(Order)
                .where(Order.order_ref == order_ref)
                .values(status="failed", failure_reason=reason, total_cents=total_cents)
            )

    async def get(self, order_ref: str) -> Order | None:
        async with self._sm() as s:
            return (await s.scalars(select(Order).where(Order.order_ref == order_ref))).one_or_none()


def _resume_interval():  # type: ignore[no-untyped-def]
    return text(f"interval '{RESUME_AFTER_SECONDS} seconds'")
