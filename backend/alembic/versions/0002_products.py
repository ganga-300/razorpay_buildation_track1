"""add products table

Hand-corrected from `alembic revision --autogenerate`. Two fixes to the
generated output:

1. The generated JSONB variant referenced a bare `Text()` that was never
   imported — it would have raised NameError on Postgres.
2. Timestamp defaults now use `sa.func.now()` instead of the SQLite-flavoured
   `(CURRENT_TIMESTAMP)` literal, so the same migration runs on both backends.

Revision ID: 0002_products
Revises: 0001_initial
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_products"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, plain JSON on SQLite — mirrors app.db.models.JSONType.
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("attributes", JSON_TYPE, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("price_minor >= 0", name="ck_products_price_non_negative"),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.create_index(
            "ix_products_active_category", ["is_active", "category"], unique=False
        )
        batch_op.create_index("ix_products_category", ["category"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_index("ix_products_category")
        batch_op.drop_index("ix_products_active_category")

    op.drop_table("products")
