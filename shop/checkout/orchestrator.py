"""Checkout orchestration, independent of HTTP and database frameworks.

The orchestrator talks to inventory, payment and order storage only through
the protocols below, so the business flow (including compensation on failure)
is unit-tested with fakes. The FastAPI app wires in httpx/SQLAlchemy
implementations.

Flow:  create pending order -> reserve stock -> charge -> confirm reservation
       -> mark order confirmed.
Compensation: if the charge fails, the reservation is released (best effort)
and the order is marked failed with a machine-readable reason.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from shop.common.outcomes import Outcome

# Connect errors and 4xx mean the processor never accepted the request; these
# outcomes mean it might have.
UNCERTAIN_PAYMENT_OUTCOMES = frozenset({Outcome.TIMEOUT, Outcome.HTTP_5XX, Outcome.BAD_RESPONSE})
RESUME_AFTER_SECONDS = 30

log = logging.getLogger("shop.checkout")


# --------------------------------------------------------------------- types
@dataclass(frozen=True)
class LineItem:
    sku: str
    qty: int


@dataclass(frozen=True)
class ReservedLine:
    sku: str
    qty: int
    unit_price_cents: int


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    lines: tuple[ReservedLine, ...]

    @property
    def total_cents(self) -> int:
        return sum(line.qty * line.unit_price_cents for line in self.lines)


@dataclass(frozen=True)
class Charge:
    charge_id: str
    status: str


@dataclass(frozen=True)
class CheckoutRequest:
    customer_id: str
    items: tuple[LineItem, ...]
    card_token: str
    currency: str = "USD"
    idempotency_key: str | None = None
    synthetic: bool = False

    def fingerprint(self) -> str:
        """Stable hash of the fields that define *what* is being bought.

        Stored with the order so a reused idempotency key with a different body
        is rejected instead of silently replaying the original order.
        """
        canonical = json.dumps(
            {
                "customer_id": self.customer_id,
                "currency": self.currency,
                "card_token": self.card_token,
                "items": sorted((i.sku, i.qty) for i in self.items),
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class CheckoutResult:
    order_ref: str
    status: str
    total_cents: int | None
    charge_id: str | None
    replayed: bool = False


@dataclass
class ExistingOrder:
    order_ref: str
    status: str
    total_cents: int | None
    charge_id: str | None
    failure_reason: str | None = None
    request_fingerprint: str | None = None
    stale: bool = False  # pending and untouched for longer than RESUME_AFTER (crashed attempt)

    @property
    def resumable(self) -> bool:
        return self.status == "unknown" or (self.status == "pending" and self.stale)


@dataclass(frozen=True)
class OrderClaim:
    """Result of atomically claiming an order (and its idempotency key).

    ``created`` is False when another request already owns the key; ``existing``
    then describes that order.
    """

    created: bool
    existing: ExistingOrder | None = None


# -------------------------------------------------------------------- errors
class CheckoutError(Exception):
    code = "checkout_error"
    http_status = 500


class InvalidOrder(CheckoutError):
    code = "invalid_order"
    http_status = 422


class OutOfStock(CheckoutError):
    code = "out_of_stock"
    http_status = 409


class PaymentDeclined(CheckoutError):
    code = "payment_declined"
    http_status = 402


@dataclass
class DependencyError(CheckoutError):
    dependency: str
    operation: str
    outcome: Outcome
    target: str
    detail: str = ""
    status_code: int | None = None
    code: str = field(default="dependency_unavailable")

    def __post_init__(self) -> None:
        super().__init__(f"{self.dependency}.{self.operation} failed: {self.outcome} ({self.detail})")

    @property
    def http_status(self) -> int:  # type: ignore[override]
        return 504 if self.outcome == Outcome.TIMEOUT else 502


class PreviousAttemptFailed(CheckoutError):
    """An idempotent replay of a request whose first attempt failed."""

    code = "previous_attempt_failed"
    http_status = 409


class RequestInProgress(CheckoutError):
    """A concurrent request with the same idempotency key is still running."""

    code = "request_in_progress"
    http_status = 409


class PaymentOutcomeUnknown(CheckoutError):
    """The charge may or may not have happened. Retry with the SAME idempotency key."""

    code = "payment_outcome_unknown"
    http_status = 504


class IdempotencyKeyReused(CheckoutError):
    code = "idempotency_key_reused"
    http_status = 422


# ----------------------------------------------------------------- protocols
class InventoryClient(Protocol):
    async def reserve(self, order_ref: str, items: tuple[LineItem, ...]) -> Reservation: ...
    async def release(self, reservation_id: str) -> None: ...
    async def release_for_order(self, order_ref: str) -> None: ...
    async def confirm(self, reservation_id: str) -> None: ...


class PaymentClient(Protocol):
    async def charge(self, order_ref: str, amount_cents: int, currency: str, card_token: str) -> Charge: ...


class OrderRepository(Protocol):
    async def claim(self, order_ref: str, request: CheckoutRequest) -> OrderClaim:
        """Insert a pending order, or report the order that already holds the key.

        Must be atomic with respect to concurrent claims of the same key.
        """
        ...

    async def try_resume(self, order_ref: str) -> bool:
        """Atomically take over an ``unknown`` or stale ``pending`` order; False if someone else did."""
        ...

    async def mark_unknown(self, order_ref: str, total_cents: int, reservation_id: str) -> None: ...

    async def mark_confirmed(self, order_ref: str, reservation: Reservation, charge: Charge) -> None: ...
    async def mark_failed(self, order_ref: str, reason: str, total_cents: int | None) -> None: ...


# --------------------------------------------------------------- orchestrator
def new_order_ref() -> str:
    return "ord_" + uuid.uuid4().hex[:16]


def validate_request(request: CheckoutRequest, max_items: int) -> None:
    if not request.items:
        raise InvalidOrder("order has no items")
    if len(request.items) > max_items:
        raise InvalidOrder(f"order has more than {max_items} distinct items")
    skus = [i.sku for i in request.items]
    if len(set(skus)) != len(skus):
        raise InvalidOrder("duplicate SKU in order")
    for item in request.items:
        if item.qty < 1 or item.qty > 50:
            raise InvalidOrder(f"invalid quantity for {item.sku}")


async def run_checkout(
    request: CheckoutRequest,
    *,
    inventory: InventoryClient,
    payment: PaymentClient,
    orders: OrderRepository,
    max_items: int,
    order_ref: str | None = None,
) -> CheckoutResult:
    validate_request(request, max_items)

    order_ref = order_ref or new_order_ref()
    claim = await orders.claim(order_ref, request)
    if not claim.created:
        assert claim.existing is not None
        existing = claim.existing
        _check_fingerprint(existing, request)
        if not (existing.resumable and await orders.try_resume(existing.order_ref)):
            return _replay(existing, request)
        # Resuming is safe: reserve is idempotent per order_ref and the charge
        # carries order_ref as its idempotency key, so nothing happens twice.
        order_ref = existing.order_ref

    try:
        reservation = await inventory.reserve(order_ref, request.items)
    except OutOfStock:
        await orders.mark_failed(order_ref, "out_of_stock", None)
        raise
    except DependencyError as exc:
        if exc.outcome in (Outcome.TIMEOUT, Outcome.HTTP_5XX, Outcome.BAD_RESPONSE):
            # The hold may have been created after we gave up waiting.
            await _release_order_best_effort(inventory, order_ref)
        await orders.mark_failed(order_ref, "inventory_unavailable", None)
        raise

    total = reservation.total_cents
    try:
        charge = await payment.charge(order_ref, total, request.currency, request.card_token)
    except DependencyError as exc:
        if exc.outcome in UNCERTAIN_PAYMENT_OUTCOMES:
            # The processor may have charged the card. Keep the stock hold and let
            # a retry with the same key settle it, instead of guessing "failed".
            await orders.mark_unknown(order_ref, total, reservation.reservation_id)
            raise PaymentOutcomeUnknown("payment outcome unknown; retry with the same Idempotency-Key") from exc
        await _release_best_effort(inventory, reservation, order_ref)
        await orders.mark_failed(order_ref, "payment_unavailable", total)
        raise
    except PaymentDeclined:
        await _release_best_effort(inventory, reservation, order_ref)
        await orders.mark_failed(order_ref, "payment_declined", total)
        raise

    try:
        await inventory.confirm(reservation.reservation_id)
    except DependencyError as exc:
        # The charge succeeded; the hold stays valid. Record and continue so the
        # customer is not charged for an order we then report as failed.
        log.warning(
            "reservation confirm failed after successful charge",
            extra={"fields": {"order_ref": order_ref, "outcome": str(exc.outcome)}},
        )

    await orders.mark_confirmed(order_ref, reservation, charge)
    return CheckoutResult(order_ref, "confirmed", total, charge.charge_id)


def _check_fingerprint(existing: ExistingOrder, request: CheckoutRequest) -> None:
    if existing.request_fingerprint and existing.request_fingerprint != request.fingerprint():
        raise IdempotencyKeyReused("idempotency key was already used for a different request")


def _replay(existing: ExistingOrder, request: CheckoutRequest) -> CheckoutResult:
    _check_fingerprint(existing, request)
    if existing.status == "confirmed":
        return CheckoutResult(
            existing.order_ref, existing.status, existing.total_cents, existing.charge_id, replayed=True
        )
    if existing.status in ("pending", "unknown"):
        raise RequestInProgress(f"order {existing.order_ref} for this idempotency key is still in progress")
    raise PreviousAttemptFailed(f"order {existing.order_ref} for this idempotency key is {existing.status}")


async def _release_order_best_effort(inventory: InventoryClient, order_ref: str) -> None:
    try:
        await inventory.release_for_order(order_ref)
    except DependencyError as exc:
        log.error(
            "failed to release possible orphaned hold after inventory failure",
            extra={"fields": {"order_ref": order_ref, "outcome": str(exc.outcome)}},
        )


async def _release_best_effort(inventory: InventoryClient, reservation: Reservation, order_ref: str) -> None:
    try:
        await inventory.release(reservation.reservation_id)
    except DependencyError as exc:
        log.error(
            "failed to release reservation after payment failure",
            extra={
                "fields": {
                    "order_ref": order_ref,
                    "reservation_id": reservation.reservation_id,
                    "outcome": str(exc.outcome),
                }
            },
        )
