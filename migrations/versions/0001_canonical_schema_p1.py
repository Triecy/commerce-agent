"""Canonical Schema, P1 subset: items, users, interactions, inventory (FR-D1).

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

interaction_type = postgresql.ENUM(
    "view", "cart", "purchase", "review", name="interaction_type", create_type=False
)


def upgrade() -> None:
    interaction_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "items",
        sa.Column("item_id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "category_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_items_price"),
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
    )

    op.create_table(
        "interactions",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("item_id", sa.Text(), sa.ForeignKey("items.item_id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", interaction_type, nullable=False),
        sa.Column("value", sa.REAL(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "item_id", "ts", "type"),
    )
    op.create_index("ix_interactions_item_id", "interactions", ["item_id"])
    op.create_index("ix_interactions_ts", "interactions", ["ts"])

    op.create_table(
        "inventory",
        sa.Column("item_id", sa.Text(), sa.ForeignKey("items.item_id"), primary_key=True),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("available >= 0", name="ck_inventory_available_nonneg"),
        sa.CheckConstraint("reserved >= 0", name="ck_inventory_reserved_nonneg"),
        comment="SIMULATED inventory (FR-D3); not real stock data",
    )


def downgrade() -> None:
    op.drop_table("inventory")
    op.drop_index("ix_interactions_ts", table_name="interactions")
    op.drop_index("ix_interactions_item_id", table_name="interactions")
    op.drop_table("interactions")
    op.drop_table("users")
    op.drop_table("items")
    interaction_type.drop(op.get_bind(), checkfirst=True)
