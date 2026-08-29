"""Catalog endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings
from app.schemas.catalog import CATALOG_SCHEMA_VERSION, CATALOG_SPEC

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# The self-describing envelope
# --------------------------------------------------------------------------


async def test_catalog_is_self_describing(client: AsyncClient) -> None:
    """An agent must be able to detect a contract change, not silently mis-parse."""
    body = (await client.get("/catalog")).json()
    assert body["schema_version"] == CATALOG_SCHEMA_VERSION
    assert body["spec"] == CATALOG_SPEC
    assert body["generated_at"]


async def test_catalog_declares_test_mode_merchant(client: AsyncClient) -> None:
    merchant = (await client.get("/catalog")).json()["merchant"]
    assert merchant["payment_provider"] == "razorpay"
    assert merchant["payment_mode"] == "test"


async def test_catalog_publishes_the_purchase_policy(client: AsyncClient) -> None:
    """Spend bounds are discoverable up front so an agent can self-limit."""
    caps = (await client.get("/catalog")).json()["capabilities"]
    policy = caps["purchase_policy"]

    assert policy["enforcement"] == "server-side"
    assert policy["auto_approve_limit"]["amount_minor"] == settings.auto_approve_limit_minor
    assert policy["per_transaction_cap"]["amount_minor"] == settings.per_transaction_cap_minor
    assert policy["daily_cap"]["amount_minor"] == settings.daily_cap_minor
    # The approval threshold and the auto-approve limit are the same boundary
    # seen from either side; they must never drift apart.
    assert (
        policy["approval_required_above"]["amount_minor"]
        == policy["auto_approve_limit"]["amount_minor"]
    )


async def test_catalog_echoes_the_query_it_answered(client: AsyncClient) -> None:
    body = (await client.get("/catalog", params={"q": "wireless", "limit": 2})).json()
    assert body["query"]["q"] == "wireless"
    assert body["query"]["limit"] == 2


# --------------------------------------------------------------------------
# Money representation
# --------------------------------------------------------------------------


async def test_prices_are_integer_minor_units_with_a_display_string(
    client: AsyncClient,
) -> None:
    products = (await client.get("/catalog")).json()["products"]
    cable = next(p for p in products if p["id"] == "prd-cable")

    assert cable["price"]["amount_minor"] == 34_900
    assert isinstance(cable["price"]["amount_minor"], int)
    assert cable["price"]["currency"] == "INR"
    assert cable["price"]["display"] == "₹349.00"


async def test_large_prices_use_indian_digit_grouping(client: AsyncClient) -> None:
    body = (await client.get("/catalog/prd-espresso")).json()
    assert body["product"]["price"]["display"] == "₹8,999.00"


# --------------------------------------------------------------------------
# Listing, ordering, visibility
# --------------------------------------------------------------------------


async def test_catalog_excludes_inactive_products(client: AsyncClient) -> None:
    body = (await client.get("/catalog")).json()
    ids = [p["id"] for p in body["products"]]
    assert "prd-retired" not in ids
    assert body["total_matching"] == 4


async def test_products_are_ordered_by_ascending_price(client: AsyncClient) -> None:
    products = (await client.get("/catalog")).json()["products"]
    prices = [p["price"]["amount_minor"] for p in products]
    assert prices == sorted(prices)


async def test_catalog_lists_its_categories(client: AsyncClient) -> None:
    body = (await client.get("/catalog")).json()
    assert body["categories"] == ["accessories", "audio", "home", "peripherals"]


async def test_each_product_carries_a_self_link(client: AsyncClient) -> None:
    products = (await client.get("/catalog")).json()["products"]
    cable = next(p for p in products if p["id"] == "prd-cable")
    assert cable["self_link"] == "/catalog/prd-cable"

    # And that link resolves.
    assert (await client.get(cable["self_link"])).status_code == 200


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


async def test_search_requires_every_token_to_match(client: AsyncClient) -> None:
    """'wireless noise' must not match a product that only mentions 'wireless'."""
    single = (await client.get("/catalog", params={"q": "wireless"})).json()
    assert {p["id"] for p in single["products"]} == {"prd-mouse", "prd-headphones"}

    both = (await client.get("/catalog", params={"q": "wireless noise"})).json()
    assert {p["id"] for p in both["products"]} == {"prd-headphones"}


async def test_search_matches_description_and_category_too(client: AsyncClient) -> None:
    by_category = (await client.get("/catalog", params={"q": "peripherals"})).json()
    assert [p["id"] for p in by_category["products"]] == ["prd-mouse"]


async def test_category_filter_is_case_insensitive(client: AsyncClient) -> None:
    body = (await client.get("/catalog", params={"category": "AUDIO"})).json()
    assert [p["id"] for p in body["products"]] == ["prd-headphones"]


async def test_price_bounds_are_inclusive(client: AsyncClient) -> None:
    body = (
        await client.get("/catalog", params={"max_price_minor": 129_900})
    ).json()
    assert {p["id"] for p in body["products"]} == {"prd-cable", "prd-mouse"}

    body = (await client.get("/catalog", params={"min_price_minor": 249_900})).json()
    assert {p["id"] for p in body["products"]} == {"prd-headphones", "prd-espresso"}


async def test_in_stock_only_filters_out_zero_stock(client: AsyncClient) -> None:
    default = (await client.get("/catalog")).json()
    assert "prd-espresso" in {p["id"] for p in default["products"]}

    filtered = (await client.get("/catalog", params={"in_stock_only": True})).json()
    assert "prd-espresso" not in {p["id"] for p in filtered["products"]}


async def test_limit_caps_results_but_total_matching_reports_the_truth(
    client: AsyncClient,
) -> None:
    body = (await client.get("/catalog", params={"limit": 2})).json()
    assert body["count"] == 2
    assert len(body["products"]) == 2
    assert body["total_matching"] == 4


async def test_limit_above_the_maximum_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/catalog", params={"limit": 5000})).status_code == 422


async def test_negative_price_bound_is_rejected(client: AsyncClient) -> None:
    assert (
        await client.get("/catalog", params={"max_price_minor": -1})
    ).status_code == 422


# --------------------------------------------------------------------------
# Single product
# --------------------------------------------------------------------------


async def test_get_product_returns_the_same_envelope(client: AsyncClient) -> None:
    body = (await client.get("/catalog/prd-headphones")).json()
    assert body["schema_version"] == CATALOG_SCHEMA_VERSION
    assert body["spec"] == CATALOG_SPEC
    assert body["product"]["id"] == "prd-headphones"
    assert body["product"]["attributes"]["anc"] is True


async def test_get_product_reports_availability(client: AsyncClient) -> None:
    in_stock = (await client.get("/catalog/prd-headphones")).json()["product"]
    assert in_stock["availability"] == {"in_stock": True, "quantity": 5}

    out = (await client.get("/catalog/prd-espresso")).json()["product"]
    assert out["availability"] == {"in_stock": False, "quantity": 0}


async def test_unknown_product_is_404(client: AsyncClient) -> None:
    resp = await client.get("/catalog/prd-does-not-exist")
    assert resp.status_code == 404
    assert "prd-does-not-exist" in resp.json()["detail"]


async def test_inactive_product_is_404_not_hidden_200(client: AsyncClient) -> None:
    assert (await client.get("/catalog/prd-retired")).status_code == 404
