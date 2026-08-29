"""Catalog query logic.

This is the single implementation of catalog search and lookup. Both the HTTP
router (`api/catalog.py`) and the agent tools (`tools/catalog.py`) call in here,
so a human browsing the API and an AI agent querying it can never see different
results or a different envelope.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utcnow
from app.db.models import Product
from app.schemas.catalog import (
    AgentProduct,
    CatalogCapabilities,
    CatalogQuery,
    CatalogResponse,
    MerchantInfo,
    Money,
    ProductResponse,
    PurchasePolicy,
)

# Upper bound on `limit`, so a hostile or confused agent cannot ask for the
# entire table in one call.
MAX_LIMIT = 100


def _merchant_info() -> MerchantInfo:
    return MerchantInfo(
        name=settings.app_name,
        currency=settings.razorpay_currency,
        payment_mode="test",
    )


def _purchase_policy() -> PurchasePolicy:
    """Publish the spend bounds so agents can self-limit before transacting."""
    currency = settings.razorpay_currency
    return PurchasePolicy(
        currency=currency,
        auto_approve_limit=Money.of(settings.auto_approve_limit_minor, currency),
        per_transaction_cap=Money.of(settings.per_transaction_cap_minor, currency),
        daily_cap=Money.of(settings.daily_cap_minor, currency),
        approval_required_above=Money.of(settings.auto_approve_limit_minor, currency),
    )


def _capabilities() -> CatalogCapabilities:
    return CatalogCapabilities(purchase_policy=_purchase_policy())


def _apply_filters(
    stmt: Select[tuple[Product]],
    *,
    q: str | None,
    category: str | None,
    min_price_minor: int | None,
    max_price_minor: int | None,
    in_stock_only: bool,
) -> Select[tuple[Product]]:
    """Apply the shared filter set to a products SELECT."""
    stmt = stmt.where(Product.is_active.is_(True))

    if q:
        # Every whitespace-separated token must appear somewhere in the record.
        # An agent asking for "wireless noise cancelling" should not match a
        # product that only mentions "wireless".
        for token in q.split():
            pattern = f"%{token}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(pattern),
                    Product.description.ilike(pattern),
                    Product.category.ilike(pattern),
                )
            )

    if category:
        stmt = stmt.where(func.lower(Product.category) == category.lower())
    if min_price_minor is not None:
        stmt = stmt.where(Product.price_minor >= min_price_minor)
    if max_price_minor is not None:
        stmt = stmt.where(Product.price_minor <= max_price_minor)
    if in_stock_only:
        stmt = stmt.where(Product.stock > 0)

    return stmt


async def search_products(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    min_price_minor: int | None = None,
    max_price_minor: int | None = None,
    in_stock_only: bool = False,
    limit: int = 50,
) -> tuple[list[Product], int]:
    """Return (page of products, total matches before limiting)."""
    limit = max(1, min(limit, MAX_LIMIT))

    filters = {
        "q": q,
        "category": category,
        "min_price_minor": min_price_minor,
        "max_price_minor": max_price_minor,
        "in_stock_only": in_stock_only,
    }

    count_stmt = _apply_filters(select(func.count()).select_from(Product), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Product), **filters)
    stmt = stmt.order_by(Product.price_minor.asc(), Product.id.asc()).limit(limit)
    products = list((await session.execute(stmt)).scalars().all())

    return products, total


async def get_product_by_id(session: AsyncSession, product_id: str) -> Product | None:
    """Look up one active product by its slug id."""
    stmt = select(Product).where(
        Product.id == product_id, Product.is_active.is_(True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_categories(session: AsyncSession) -> list[str]:
    """Distinct categories across the active catalog."""
    stmt = (
        select(Product.category)
        .where(Product.is_active.is_(True))
        .distinct()
        .order_by(Product.category)
    )
    return list((await session.execute(stmt)).scalars().all())


async def build_catalog_response(
    session: AsyncSession,
    *,
    prefix: str = "",
    q: str | None = None,
    category: str | None = None,
    min_price_minor: int | None = None,
    max_price_minor: int | None = None,
    in_stock_only: bool = False,
    limit: int = 50,
) -> CatalogResponse:
    """Assemble the full agent-readable catalog document."""
    products, total = await search_products(
        session,
        q=q,
        category=category,
        min_price_minor=min_price_minor,
        max_price_minor=max_price_minor,
        in_stock_only=in_stock_only,
        limit=limit,
    )
    categories = await list_categories(session)

    return CatalogResponse(
        generated_at=utcnow(),
        merchant=_merchant_info(),
        capabilities=_capabilities(),
        query=CatalogQuery(
            q=q,
            category=category,
            min_price_minor=min_price_minor,
            max_price_minor=max_price_minor,
            in_stock_only=in_stock_only,
            limit=limit,
        ),
        count=len(products),
        total_matching=total,
        categories=categories,
        products=[AgentProduct.from_orm_product(p, prefix=prefix) for p in products],
    )


def build_product_response(product: Product, *, prefix: str = "") -> ProductResponse:
    """Wrap a single product in the same self-describing envelope."""
    return ProductResponse(
        generated_at=utcnow(),
        merchant=_merchant_info(),
        product=AgentProduct.from_orm_product(product, prefix=prefix),
    )
