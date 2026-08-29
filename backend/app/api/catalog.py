"""Catalog endpoints — the merchant's agent-readable interface.

`GET /catalog` is deliberately a *document*, not a bare array: it carries a
schema version, the merchant identity, the purchase policy, and the echoed
query alongside the products, so an agent that fetches this one URL has
everything it needs to decide what it can buy and under what constraints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.catalog import CatalogResponse, ProductResponse
from app.services.catalog import (
    MAX_LIMIT,
    build_catalog_response,
    build_product_response,
    get_product_by_id,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "",
    response_model=CatalogResponse,
    summary="Machine-readable product catalog",
    description=(
        "Returns the full agent-readable catalog document: schema version, "
        "merchant identity, published purchase policy (spend caps and the "
        "approval threshold), and the matching products."
    ),
)
async def get_catalog(
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, description="Free-text search; every token must match"),
    category: str | None = Query(default=None, description="Exact category, case-insensitive"),
    min_price_minor: int | None = Query(default=None, ge=0, description="Inclusive lower bound, minor units"),
    max_price_minor: int | None = Query(default=None, ge=0, description="Inclusive upper bound, minor units"),
    in_stock_only: bool = Query(default=False, description="Exclude out-of-stock items"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> CatalogResponse:
    """Search and return the catalog document."""
    return await build_catalog_response(
        session,
        q=q,
        category=category,
        min_price_minor=min_price_minor,
        max_price_minor=max_price_minor,
        in_stock_only=in_stock_only,
        limit=limit,
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Single product detail",
    responses={404: {"description": "No active product with that id"}},
)
async def get_product(
    product_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    """Fetch one product by its slug id."""
    product = await get_product_by_id(session, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active product with id {product_id!r}",
        )
    return build_product_response(product)
