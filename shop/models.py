"""SQLAlchemy models for the demo shop database.

Ownership by convention: ``products``/``reservations`` belong to inventory,
``orders`` to checkout, ``config_versions``/``change_events`` to the config
plane. One database keeps the demo small; the boundaries are enforced in code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("stock >= 0", name="ck_products_stock_nonnegative"),
        CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
    )

    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    stock: Mapped[int] = mapped_column(Integer)
    seed_stock: Mapped[int] = mapped_column(Integer)


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # One reservation per order makes reserve idempotent, so checkout can retry it.
    order_ref: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(16))  # held | committed | released
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    items: Mapped[list[ReservationItem]] = relationship(back_populates="reservation", lazy="selectin")


class ReservationItem(Base):
    __tablename__ = "reservation_items"

    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    reservation: Mapped[Reservation] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    order_ref: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # pending | confirmed | failed
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    total_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    reservation_id: Mapped[str | None] = mapped_column(String(40))
    charge_id: Mapped[str | None] = mapped_column(String(40))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", lazy="selectin")


class OrderItem(Base):
    __tablename__ = "order_items"

    order_ref: Mapped[str] = mapped_column(ForeignKey("orders.order_ref"), primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


class ConfigVersion(Base):
    """Immutable, append-only runtime configuration versions.

    Exactly one row per service is active (partial unique index). Rollback is a
    roll-forward: it creates a new version copying an older payload, so history
    is never rewritten.
    """

    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("service", "version", name="uq_config_versions_service_version"),
        Index(
            "uq_config_versions_one_active",
            "service",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChangeEvent(Base):
    """Operational change history (config changes, deploys, flag flips)."""

    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    service: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))  # config_change | deploy | flag_change
    summary: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64))
    from_version: Mapped[int | None] = mapped_column(Integer)
    to_version: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
