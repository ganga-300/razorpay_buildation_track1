"""Catalog tools exposed to the purchasing agent.

These call `services/catalog.py` directly rather than issuing HTTP requests back
into this same process. The agent therefore sees byte-identical payloads to the
`/catalog` endpoints — same schema version, same money representation, same
published purchase policy — without a pointless network hop that would add a
failure mode and make every agent turn slower.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.catalog import (
    MAX_LIMIT,
    build_catalog_response,
    build_product_response,
    get_product_by_id,
)
from app.tools.base import ToolError, ToolSpec, registry

SEARCH_CATALOG_DESCRIPTION = """\
Search the merchant's product catalog. Use this whenever the buyer names, \
describes, or hints at something they want, and before proposing any purchase.

Returns matching products plus the merchant's published purchase policy — the \
auto-approve limit, the per-transaction cap, and the daily cap. Read that policy \
and take it into account before proposing an order.

All money is in MINOR UNITS (paise: 249900 means ₹2,499.00). Compare and filter \
using `amount_minor`; the `display` string is for showing the buyer only."""

GET_PRODUCT_DESCRIPTION = """\
Fetch full detail for one product by its exact id (for example \
'prd-anc-headphones'). Use this after search_catalog to confirm the price and \
stock of the specific item you are about to propose ordering.

Prices are in MINOR UNITS (paise)."""


async def search_catalog(
    session: AsyncSession,
    query: str | None = None,
    category: str | None = None,
    max_price_minor: int | None = None,
    min_price_minor: int | None = None,
    in_stock_only: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    """Search the catalog and return the agent-readable document."""
    if limit < 1 or limit > MAX_LIMIT:
        raise ToolError(
            "invalid_arguments",
            f"limit must be between 1 and {MAX_LIMIT}, got {limit}",
        )
    if (
        min_price_minor is not None
        and max_price_minor is not None
        and min_price_minor > max_price_minor
    ):
        raise ToolError(
            "invalid_arguments",
            "min_price_minor cannot exceed max_price_minor",
        )

    response = await build_catalog_response(
        session,
        q=query,
        category=category,
        min_price_minor=min_price_minor,
        max_price_minor=max_price_minor,
        in_stock_only=in_stock_only,
        limit=limit,
    )
    return response.model_dump(mode="json")


async def get_product(session: AsyncSession, product_id: str) -> dict[str, Any]:
    """Fetch one product by id."""
    if not product_id or not product_id.strip():
        raise ToolError("invalid_arguments", "product_id is required")

    product = await get_product_by_id(session, product_id.strip())
    if product is None:
        raise ToolError(
            "product_not_found",
            f"No active product with id {product_id!r}. Use search_catalog to find valid ids.",
            details={"product_id": product_id},
        )

    return build_product_response(product).model_dump(mode="json")


registry.register(
    ToolSpec(
        name="search_catalog",
        description=SEARCH_CATALOG_DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Free-text search. Every whitespace-separated token must "
                        "appear in the product's name, description, or category. "
                        "Prefer two or three specific words over a long sentence."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": "Restrict to one category. Categories are listed in every response.",
                },
                "max_price_minor": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Inclusive maximum unit price in minor units (paise).",
                },
                "min_price_minor": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Inclusive minimum unit price in minor units (paise).",
                },
                "in_stock_only": {
                    "type": "boolean",
                    "description": "Exclude out-of-stock products. Defaults to true.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "description": "Maximum products to return. Defaults to 10.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=search_catalog,
    )
)

registry.register(
    ToolSpec(
        name="get_product",
        description=GET_PRODUCT_DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "Exact product id, e.g. 'prd-anc-headphones'.",
                }
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
        handler=get_product,
    )
)
