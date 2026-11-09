import asyncio

import pytest

from shop.checkout.orchestrator import (
    Charge,
    CheckoutRequest,
    DependencyError,
    ExistingOrder,
    IdempotencyKeyReused,
    InvalidOrder,
    LineItem,
    OrderClaim,
    OutOfStock,
    PaymentDeclined,
    PaymentOutcomeUnknown,
    PreviousAttemptFailed,
    RequestInProgress,
    Reservation,
    ReservedLine,
    run_checkout,
)
from shop.common.outcomes import Outcome


class FakeInventory:
    def __init__(self, fail_reserve=None, fail_release=False):
        self.fail_reserve = fail_reserve
        self.fail_release = fail_release
        self.calls = []

    async def reserve(self, order_ref, items):
        self.calls.append("reserve")
        if self.fail_reserve:
            raise self.fail_reserve
        return Reservation("res_1", tuple(ReservedLine(i.sku, i.qty, 1000) for i in items))

    async def release_for_order(self, order_ref):
        self.calls.append("release_for_order")

    async def release(self, reservation_id):
        self.calls.append("release")
        if self.fail_release:
            raise DependencyError("inventory", "release", Outcome.TIMEOUT, "inventory:8001")

    async def confirm(self, reservation_id):
        self.calls.append("confirm")


class FakePayment:
    def __init__(self, fail=None):
        self.fail = fail
        self.charges = 0

    async def charge(self, order_ref, amount_cents, currency, card_token):
        self.charges += 1
        if self.fail:
            raise self.fail
        return Charge("ch_1", "succeeded")


class FakeOrders:
    """In-memory repository whose claim is atomic, like INSERT ... ON CONFLICT."""

    def __init__(self, existing=None):
        self.existing = existing
        self.state = {}
        self.by_key = {}
        self.stale = False

    async def try_resume(self, order_ref):
        status, _ = self.state[order_ref]
        if status == "unknown" or self.stale:
            self.state[order_ref] = ("pending", None)
            return True
        return False

    async def mark_unknown(self, order_ref, total_cents, reservation_id):
        self.state[order_ref] = ("unknown", "payment_outcome_unknown")

    async def claim(self, order_ref, request):
        if self.existing is not None:
            return OrderClaim(created=False, existing=self.existing)
        key = request.idempotency_key
        if key and key in self.by_key:
            ref, fp = self.by_key[key]
            status, reason = self.state[ref]
            return OrderClaim(False, ExistingOrder(ref, status, None, None, reason, fp, stale=self.stale))
        if key:
            self.by_key[key] = (order_ref, request.fingerprint())
        self.state[order_ref] = ("pending", None)
        return OrderClaim(created=True)

    async def mark_confirmed(self, order_ref, reservation, charge):
        self.state[order_ref] = ("confirmed", None)

    async def mark_failed(self, order_ref, reason, total_cents):
        self.state[order_ref] = ("failed", reason)


REQ = CheckoutRequest("c1", (LineItem("SKU-1", 2), LineItem("SKU-2", 1)), "tok_test_visa")


def run(request=REQ, **kw):
    defaults = dict(inventory=FakeInventory(), payment=FakePayment(), orders=FakeOrders(), max_items=20)
    defaults.update(kw)
    return asyncio.run(run_checkout(request, **defaults))


def test_happy_path_confirms_and_totals():
    inv, orders = FakeInventory(), FakeOrders()
    result = run(inventory=inv, orders=orders)
    assert result.status == "confirmed" and result.total_cents == 3000
    assert inv.calls == ["reserve", "confirm"]
    assert orders.state[result.order_ref] == ("confirmed", None)


def test_payment_connect_error_releases_stock_and_fails_order():
    inv, orders = FakeInventory(), FakeOrders()
    err = DependencyError("payment", "charge", Outcome.CONNECT_ERROR, "payment:8020", "refused")
    with pytest.raises(DependencyError) as exc:
        run(inventory=inv, payment=FakePayment(fail=err), orders=orders)
    assert exc.value.http_status == 502
    assert inv.calls == ["reserve", "release"]
    ((status, reason),) = orders.state.values()
    assert (status, reason) == ("failed", "payment_unavailable")


def test_timeout_maps_to_504():
    err = DependencyError("payment", "charge", Outcome.TIMEOUT, "payment:8002")
    assert err.http_status == 504


def test_declined_card_releases_stock():
    inv, orders = FakeInventory(), FakeOrders()
    with pytest.raises(PaymentDeclined):
        run(inventory=inv, payment=FakePayment(fail=PaymentDeclined("no")), orders=orders)
    assert "release" in inv.calls
    assert list(orders.state.values()) == [("failed", "payment_declined")]


def test_release_failure_does_not_mask_payment_error():
    inv = FakeInventory(fail_release=True)
    err = DependencyError("payment", "charge", Outcome.CONNECT_ERROR, "payment:8002")
    with pytest.raises(DependencyError) as exc:
        run(inventory=inv, payment=FakePayment(fail=err))
    assert exc.value.dependency == "payment"


def test_out_of_stock_never_charges():
    pay, orders = FakePayment(), FakeOrders()
    with pytest.raises(OutOfStock):
        run(inventory=FakeInventory(fail_reserve=OutOfStock("x")), payment=pay, orders=orders)
    assert pay.charges == 0
    assert list(orders.state.values()) == [("failed", "out_of_stock")]


def test_inventory_timeout_releases_possible_orphan_hold():
    err = DependencyError("inventory", "reserve", Outcome.TIMEOUT, "inventory:8001")
    inv, orders = FakeInventory(fail_reserve=err), FakeOrders()
    with pytest.raises(DependencyError):
        run(inventory=inv, orders=orders)
    assert inv.calls == ["reserve", "release_for_order"]
    assert list(orders.state.values()) == [("failed", "inventory_unavailable")]


def test_inventory_connect_error_does_not_attempt_release():
    # Nothing can have been reserved if the connection never opened.
    err = DependencyError("inventory", "reserve", Outcome.CONNECT_ERROR, "inventory:8001")
    inv = FakeInventory(fail_reserve=err)
    with pytest.raises(DependencyError):
        run(inventory=inv)
    assert inv.calls == ["reserve"]


def test_concurrent_duplicate_requests_charge_once():
    """Two simultaneous requests with one key: exactly one charge, the other is told to retry."""
    req = CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k-race")
    orders, pay = FakeOrders(), FakePayment()

    class SlowInventory(FakeInventory):
        async def reserve(self, order_ref, items):
            await asyncio.sleep(0.01)  # keep the first order pending while the second arrives
            return await super().reserve(order_ref, items)

    async def both():
        kw = dict(inventory=SlowInventory(), payment=pay, orders=orders, max_items=20)
        return await asyncio.gather(run_checkout(req, **kw), run_checkout(req, **kw), return_exceptions=True)

    results = asyncio.run(both())
    confirmed = [r for r in results if not isinstance(r, Exception)]
    in_progress = [r for r in results if isinstance(r, RequestInProgress)]
    assert len(confirmed) == 1 and len(in_progress) == 1
    assert pay.charges == 1


def test_concurrent_duplicate_replays_after_first_completes():
    req = CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k-seq")
    orders, pay = FakeOrders(), FakePayment()
    first = run(request=req, orders=orders, payment=pay)
    orders.state[first.order_ref] = ("confirmed", None)
    second = run(request=req, orders=orders, payment=pay)
    assert second.replayed and second.order_ref == first.order_ref and pay.charges == 1


def test_reused_key_with_different_body_is_rejected():
    orders = FakeOrders()
    run(
        request=CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k"),
        orders=orders,
    )
    with pytest.raises(IdempotencyKeyReused):
        run(
            request=CheckoutRequest("c1", (LineItem("SKU-1", 5),), "tok_test_visa", idempotency_key="k"),
            orders=orders,
        )


def test_fingerprint_ignores_item_order():
    a = CheckoutRequest("c", (LineItem("A", 1), LineItem("B", 2)), "tok_test_visa")
    b = CheckoutRequest("c", (LineItem("B", 2), LineItem("A", 1)), "tok_test_visa")
    assert a.fingerprint() == b.fingerprint()


def test_idempotent_replay_returns_original_without_charging():
    req = CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k1")
    pay = FakePayment()
    existing = ExistingOrder("ord_old", "confirmed", 1000, "ch_old")
    result = run(request=req, payment=pay, orders=FakeOrders(existing=existing))
    assert result.replayed and result.order_ref == "ord_old" and pay.charges == 0


def test_replay_of_failed_attempt_is_rejected():
    req = CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k1")
    existing = ExistingOrder("ord_old", "failed", None, None, "payment_unavailable")
    with pytest.raises(PreviousAttemptFailed):
        run(request=req, orders=FakeOrders(existing=existing))


@pytest.mark.parametrize("items", [(), (LineItem("A", 1), LineItem("A", 1)), (LineItem("A", 0),)])
def test_invalid_orders(items):
    with pytest.raises(InvalidOrder):
        run(request=CheckoutRequest("c", items, "tok_test_visa"))


KEYED = CheckoutRequest("c1", (LineItem("SKU-1", 1),), "tok_test_visa", idempotency_key="k-unknown")


def test_payment_timeout_is_unknown_not_failed_and_keeps_hold():
    inv, orders = FakeInventory(), FakeOrders()
    err = DependencyError("payment", "charge", Outcome.TIMEOUT, "payment:8002")
    with pytest.raises(PaymentOutcomeUnknown) as exc:
        run(request=KEYED, inventory=inv, payment=FakePayment(fail=err), orders=orders)
    assert exc.value.http_status == 504
    assert "release" not in inv.calls  # the card may have been charged; keep the stock
    assert list(orders.state.values()) == [("unknown", "payment_outcome_unknown")]


def test_retry_after_unknown_resumes_same_order():
    inv, orders, pay = FakeInventory(), FakeOrders(), FakePayment()
    pay.fail = DependencyError("payment", "charge", Outcome.TIMEOUT, "payment:8002")
    with pytest.raises(PaymentOutcomeUnknown):
        run(request=KEYED, inventory=inv, payment=pay, orders=orders)
    first_ref = next(iter(orders.state))
    pay.fail = None
    result = run(request=KEYED, inventory=inv, payment=pay, orders=orders)
    assert result.order_ref == first_ref and result.status == "confirmed"


def test_connect_error_to_payment_is_definitive_failure():
    inv, orders = FakeInventory(), FakeOrders()
    err = DependencyError("payment", "charge", Outcome.CONNECT_ERROR, "payment:8020")
    with pytest.raises(DependencyError):
        run(request=KEYED, inventory=inv, payment=FakePayment(fail=err), orders=orders)
    assert "release" in inv.calls
    assert list(orders.state.values()) == [("failed", "payment_unavailable")]


def test_stale_pending_after_crash_is_resumed():
    orders = FakeOrders()
    first_ref = "ord_crashed"
    orders.by_key["k-unknown"] = (first_ref, KEYED.fingerprint())
    orders.state[first_ref] = ("pending", None)  # process died after claiming
    with pytest.raises(RequestInProgress):  # fresh pending: someone may still be working on it
        run(request=KEYED, orders=orders)
    orders.stale = True
    assert run(request=KEYED, orders=orders).order_ref == first_ref
