"""initial shop schema

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("sku", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("stock", sa.Integer, nullable=False),
        sa.Column("seed_stock", sa.Integer, nullable=False),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_nonnegative"),
        sa.CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("order_ref", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reservations_order_ref", "reservations", ["order_ref"])
    op.create_table(
        "reservation_items",
        sa.Column("reservation_id", sa.String(40), sa.ForeignKey("reservations.id"), primary_key=True),
        sa.Column("sku", sa.String(32), sa.ForeignKey("products.sku"), primary_key=True),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
    )
    op.create_table(
        "orders",
        sa.Column("order_ref", sa.String(40), primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_reason", sa.String(64)),
        sa.Column("total_cents", sa.Integer),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("reservation_id", sa.String(40)),
        sa.Column("charge_id", sa.String(40)),
        sa.Column("idempotency_key", sa.String(80), unique=True),
        sa.Column("synthetic", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_table(
        "order_items",
        sa.Column("order_ref", sa.String(40), sa.ForeignKey("orders.order_ref"), primary_key=True),
        sa.Column("sku", sa.String(32), primary_key=True),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("unit_price_cents", sa.Integer),
    )
    op.create_table(
        "config_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("author", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("service", "version", name="uq_config_versions_service_version"),
    )
    op.create_index(
        "uq_config_versions_one_active",
        "config_versions",
        ["service"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_table(
        "change_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("from_version", sa.Integer),
        sa.Column("to_version", sa.Integer),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_change_events_occurred_at", "change_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("change_events")
    op.drop_index("uq_config_versions_one_active", table_name="config_versions")
    op.drop_table("config_versions")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("reservation_items")
    op.drop_table("reservations")
    op.drop_table("products")
