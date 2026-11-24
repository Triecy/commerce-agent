"""Canonical Schema, P1 subset (SPEC §5.2): items, users, interactions, inventory.

The Alembic migrations in ``migrations/`` are the source of truth for the database;
these models mirror them, and an integration test (``alembic check``) fails if the two
drift apart. Tables owned by later phases are added by their own migrations:
``item_chunks`` (P3, FR-K1), ``reservations`` (P4, FR-I1), experiment tables (P4,
FR-X3) and ``outbox`` (P5, FR-E2).
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InteractionType(enum.StrEnum):
    VIEW = "view"
    CART = "cart"
    PURCHASE = "purchase"
    REVIEW = "review"


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (CheckConstraint("price IS NULL OR price >= 0", name="ck_items_price"),)

    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    category_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    brand: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_item_id", "item_id"),
        Index("ix_interactions_ts", "ts"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    type: Mapped[InteractionType] = mapped_column(
        Enum(
            InteractionType,
            name="interaction_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        primary_key=True,
    )
    value: Mapped[float | None] = mapped_column(REAL)


class Inventory(Base):
    """SIMULATED stock (FR-D3). Mutated only through the inventory module from P4 on."""

    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("available >= 0", name="ck_inventory_available_nonneg"),
        CheckConstraint("reserved >= 0", name="ck_inventory_reserved_nonneg"),
        {"comment": "SIMULATED inventory (FR-D3); not real stock data"},
    )

    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), primary_key=True)
    available: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
