"""ORM models.

Money is stored exclusively in **minor units** (paise for INR) as integers.
Floats are never used for money anywhere in this codebase, and Razorpay's Orders
API expects minor units too, so this representation passes straight through
without conversion.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, utcnow

# Portable JSON: JSONB on Postgres (indexable, binary), plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")

__all__ = ["Base", "TimestampMixin", "utcnow", "Product"]


class Product(Base, TimestampMixin):
    """A merchant catalog item, exposed to AI agents as a machine-readable record.

    The primary key is a human- and agent-legible slug (``prd-anc-headphones``)
    rather than an opaque integer. Agents quote product ids in conversation and
    those same ids land in the audit trail, so a readable id makes every
    downstream artifact easier to inspect.
    """

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Minor units. 249900 == INR 2,499.00
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Free-form structured attributes (brand, colour, warranty...). Named
    # `attributes` rather than `metadata` because SQLAlchemy reserves
    # `Base.metadata` on every declarative class.
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
        Index("ix_products_active_category", "is_active", "category"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Product {self.id} {self.name!r} {self.price_minor}{self.currency}>"

    @property
    def in_stock(self) -> bool:
        return self.stock > 0
