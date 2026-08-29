"""Agent tool tests.

These exercise the tools the way the agent will: through `execute_tool`, which
must always return an envelope and never raise.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.catalog import CATALOG_SPEC
from app.tools import execute_tool

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# search_catalog
# --------------------------------------------------------------------------


async def test_search_catalog_returns_a_success_envelope(db_session: AsyncSession) -> None:
    result = await execute_tool("search_catalog", db_session, {"query": "wireless"})
    assert result["ok"] is True
    assert result["data"]["spec"] == CATALOG_SPEC


async def test_search_catalog_defaults_to_in_stock_only(db_session: AsyncSession) -> None:
    """The agent should not propose something the merchant cannot ship."""
    result = await execute_tool("search_catalog", db_session, {})
    ids = {p["id"] for p in result["data"]["products"]}
    assert "prd-espresso" not in ids


async def test_search_catalog_surfaces_the_purchase_policy(
    db_session: AsyncSession,
) -> None:
    """The agent learns its spend bounds from the same call that finds products."""
    result = await execute_tool("search_catalog", db_session, {"query": "mouse"})
    policy = result["data"]["capabilities"]["purchase_policy"]
    assert policy["enforcement"] == "server-side"
    assert policy["per_transaction_cap"]["amount_minor"] > 0


async def test_search_catalog_honours_a_price_ceiling(db_session: AsyncSession) -> None:
    result = await execute_tool(
        "search_catalog", db_session, {"max_price_minor": 129_900}
    )
    assert {p["id"] for p in result["data"]["products"]} == {"prd-cable", "prd-mouse"}


async def test_search_catalog_rejects_an_inverted_price_range(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool(
        "search_catalog",
        db_session,
        {"min_price_minor": 500_000, "max_price_minor": 1_000},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


async def test_search_catalog_rejects_an_out_of_range_limit(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool("search_catalog", db_session, {"limit": 9_999})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


async def test_empty_result_is_a_success_not_an_error(db_session: AsyncSession) -> None:
    """No matches is a fact to report to the buyer, not a failure."""
    result = await execute_tool("search_catalog", db_session, {"query": "helicopter"})
    assert result["ok"] is True
    assert result["data"]["products"] == []
    assert result["data"]["total_matching"] == 0


# --------------------------------------------------------------------------
# get_product
# --------------------------------------------------------------------------


async def test_get_product_returns_the_product(db_session: AsyncSession) -> None:
    result = await execute_tool(
        "get_product", db_session, {"product_id": "prd-headphones"}
    )
    assert result["ok"] is True
    assert result["data"]["product"]["price"]["amount_minor"] == 249_900


async def test_get_product_tolerates_surrounding_whitespace(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool(
        "get_product", db_session, {"product_id": "  prd-cable  "}
    )
    assert result["ok"] is True


async def test_unknown_product_is_a_handled_error_with_a_recovery_hint(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool("get_product", db_session, {"product_id": "prd-nope"})
    assert result["ok"] is False
    assert result["error"]["code"] == "product_not_found"
    assert result["error"]["retryable"] is False
    # The message must tell the model how to recover.
    assert "search_catalog" in result["error"]["message"]


async def test_inactive_product_is_not_reachable_by_the_agent(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool("get_product", db_session, {"product_id": "prd-retired"})
    assert result["ok"] is False
    assert result["error"]["code"] == "product_not_found"


async def test_blank_product_id_is_rejected(db_session: AsyncSession) -> None:
    result = await execute_tool("get_product", db_session, {"product_id": "   "})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


# --------------------------------------------------------------------------
# Executor robustness — the agent loop must never die
# --------------------------------------------------------------------------


async def test_unknown_tool_returns_an_envelope_rather_than_raising(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool("delete_everything", db_session, {})
    assert result["ok"] is False
    assert result["error"]["code"] == "unknown_tool"
    # The model is told what it may call instead.
    assert "search_catalog" in result["error"]["message"]


async def test_hallucinated_arguments_are_dropped_not_fatal(
    db_session: AsyncSession,
) -> None:
    """Models occasionally invent a plausible extra parameter."""
    result = await execute_tool(
        "search_catalog",
        db_session,
        {"query": "wireless", "colour": "red", "sort_by": "relevance"},
    )
    assert result["ok"] is True
    assert result["data"]["products"]


async def test_missing_required_argument_is_a_handled_error(
    db_session: AsyncSession,
) -> None:
    result = await execute_tool("get_product", db_session, {})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
