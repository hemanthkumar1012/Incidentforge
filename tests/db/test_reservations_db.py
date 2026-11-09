"""Inventory reservation idempotency through the real FastAPI app and PostgreSQL.

Concurrent requests run in separate threads, each with its own TestClient, so the
outcome is decided by the unique index on reservations.order_ref.
"""

from __future__ import annotations

import importlib
import os
import threading
import uuid

import pytest

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def inventory_app(databases):
    os.environ.update({"SHOP_DATABASE_URL": databases["shop"], "LAB_ADMIN_TOKEN": "t-lab-token"})
    module = importlib.import_module("shop.inventory.app")
    return module.app


def stock(client, sku="SKU-1002"):
    return next(p["stock"] for p in client.get("/api/products").json()["products"] if p["sku"] == sku)


def test_concurrent_duplicate_reserve_decrements_once(inventory_app):
    from fastapi.testclient import TestClient

    order_ref = "ord_" + uuid.uuid4().hex[:16]
    body = {"order_ref": order_ref, "items": [{"sku": "SKU-1002", "qty": 2}]}
    with TestClient(inventory_app) as probe:
        before = stock(probe)
    barrier, statuses = threading.Barrier(4), []

    def worker():
        with TestClient(inventory_app) as client:
            barrier.wait()
            statuses.append(client.post("/api/reservations", json=body).status_code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with TestClient(inventory_app) as probe:
        assert stock(probe) == before - 2
    assert sorted(statuses) == [200, 200, 200, 201]


def test_retry_returns_existing_hold_and_conflicting_items_rejected(inventory_app):
    from fastapi.testclient import TestClient

    order_ref = "ord_" + uuid.uuid4().hex[:16]

    def body(qty):
        return {"order_ref": order_ref, "items": [{"sku": "SKU-1003", "qty": qty}]}

    with TestClient(inventory_app) as client:
        first = client.post(
            "/api/reservations", json={"order_ref": order_ref, "items": [{"sku": "SKU-1003", "qty": 1}]}
        )
        retry = client.post(
            "/api/reservations", json={"order_ref": order_ref, "items": [{"sku": "SKU-1003", "qty": 1}]}
        )
        other = client.post(
            "/api/reservations", json={"order_ref": order_ref, "items": [{"sku": "SKU-1003", "qty": 5}]}
        )
        released = client.post(f"/api/orders/{order_ref}/reservation/release")
        released_again = client.post(f"/api/orders/{order_ref}/reservation/release")
        missing = client.post("/api/orders/ord_doesnotexist/reservation/release")
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.json()["reservation_id"] == first.json()["reservation_id"]
    assert other.status_code == 409 and other.json()["error"]["code"] == "order_ref_conflict"
    assert released.status_code == 200 and released_again.status_code == 200  # idempotent
    assert missing.status_code == 404


def test_admin_hooks_require_token(inventory_app):
    from fastapi.testclient import TestClient

    with TestClient(inventory_app) as client:
        assert client.post("/admin/restock").status_code == 403
        assert client.post("/admin/restock", headers={"X-Lab-Token": "wrong"}).status_code == 403
        assert client.post("/admin/restock", headers={"X-Lab-Token": "t-lab-token"}).status_code == 200
