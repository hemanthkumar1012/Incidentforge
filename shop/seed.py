"""Idempotent seed: synthetic catalogue and the baseline checkout config.

Run:  python -m shop.seed
All data is synthetic. Re-running is safe: products are upserted and the
baseline config is written only if no checkout config exists yet.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from shop.config_admin import apply_config, get_active
from shop.db import make_sync_engine
from shop.models import Product

PRODUCTS = [
    ("SKU-1001", "Ceramic pour-over dripper", 2400, 500),
    ("SKU-1002", "Stainless steel kettle", 4800, 500),
    ("SKU-1003", "Burr coffee grinder", 9900, 300),
    ("SKU-1004", "Paper filters (100)", 600, 2000),
    ("SKU-1005", "Glass carafe 600ml", 2800, 400),
    ("SKU-1006", "Digital scale", 3500, 400),
    ("SKU-1007", "Insulated tumbler", 2200, 800),
    ("SKU-1008", "Single-origin beans 250g", 1600, 1500),
]

BASELINE_CHECKOUT_CONFIG = {
    "payment_url": "http://payment:8002",
    "inventory_url": "http://inventory:8001",
    "payment_timeout_s": 2.0,
    "inventory_timeout_s": 2.0,
    "max_items_per_order": 20,
    "currency": "USD",
}


# The validation sandbox must never point at production hosts; its baseline
# uses the sandbox service names (which only resolve on the sandbox network).
SANDBOX_CHECKOUT_CONFIG = {
    **BASELINE_CHECKOUT_CONFIG,
    "payment_url": "http://sandbox-payment:8002",
    "inventory_url": "http://sandbox-inventory:8001",
}


def seed(session: Session, baseline: dict[str, object] = BASELINE_CHECKOUT_CONFIG) -> dict[str, object]:
    for sku, name, price, stock in PRODUCTS:
        stmt = insert(Product).values(
            sku=sku, name=name, price_cents=price, currency="USD", stock=stock, seed_stock=stock
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Product.sku],
                set_={
                    "name": stmt.excluded.name,
                    "price_cents": stmt.excluded.price_cents,
                    "seed_stock": stmt.excluded.seed_stock,
                },
            )
        )
    created_config = False
    if get_active(session, "checkout") is None:
        apply_config(
            session,
            "checkout",
            dict(baseline),
            author="bootstrap",
            reason="initial configuration",
            summary="checkout initial configuration",
        )
        created_config = True
    return {"products": len(PRODUCTS), "baseline_config_created": created_config}


def main() -> int:
    parser = argparse.ArgumentParser(description="seed the shop database (synthetic data)")
    parser.add_argument("--sandbox", action="store_true", help="seed the validation sandbox baseline")
    args = parser.parse_args()
    url = os.environ.get("SHOP_MIGRATION_DATABASE_URL")
    if not url:
        print("SHOP_MIGRATION_DATABASE_URL is not set", file=sys.stderr)
        return 2
    engine = make_sync_engine(url)
    with Session(engine) as session, session.begin():
        result = seed(session, SANDBOX_CHECKOUT_CONFIG if args.sandbox else BASELINE_CHECKOUT_CONFIG)
    print(f"seed complete: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
