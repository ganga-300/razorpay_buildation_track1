"""MCP server tests.

The point of the MCP surface is that a *different* agent can transact with this
merchant. The point of these tests is that doing so buys the caller no
privileges: same guardrails, same audit trail, same refusals.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditAction, AuditDecision, AuditLog, Order, OrderStatus
from app.mcp.server import MCP_CONVERSATION_PREFIX, build_server
from app.tools import registry
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


async def call(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke an MCP tool and return the structured envelope."""
    server = build_server()
    result = await server.call_tool(name, args or {})
    return result.structured_content


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


async def test_every_registered_tool_is_exposed_over_mcp() -> None:
    """Drift guard.

    A tool added for our own agent but not surfaced here would mean the
    merchant is transactable by us and not by anyone else — which is precisely
    the gap this milestone exists to close.
    """
    tools = {t.name for t in await build_server().list_tools()}
    missing = set(registry.names()) - tools
    assert not missing, f"registered but not exposed over MCP: {sorted(missing)}"


async def test_the_policy_tool_is_discoverable() -> None:
    """An external agent must be able to read the limits before it tries to buy."""
    tools = {t.name for t in await build_server().list_tools()}
    assert "get_purchase_policy" in tools


async def test_tools_advertise_usable_schemas() -> None:
    for tool in await build_server().list_tools():
        schema = tool.input_schema or {}
        assert schema.get("type") == "object", tool.name
        assert tool.description, f"{tool.name} has no description"


async def test_create_order_does_not_expose_conversation_id() -> None:
    """The caller must not be able to attribute its order to another buyer.

    Same reasoning as the internal agent: an id supplied by the caller is an id
    a prompt injection can forge.
    """
    tools = {t.name: t for t in await build_server().list_tools()}
    params = set((tools["create_order"].input_schema or {}).get("properties") or {})
    assert params == {"product_id", "quantity", "idempotency_key"}
    assert "conversation_id" not in params


# --------------------------------------------------------------------------
# Reading the catalog
# --------------------------------------------------------------------------


async def test_search_returns_seeded_products(db_session: AsyncSession) -> None:
    env = await call("search_catalog", {"query": "cable"})
    assert env["ok"] is True
    assert [p["id"] for p in env["data"]["products"]] == ["prd-cable"]


async def test_policy_reports_the_live_limits(db_session: AsyncSession) -> None:
    env = await call("get_purchase_policy")
    data = env["data"]
    assert data["auto_approve_limit"]["display"] == "₹500.00"
    assert data["per_transaction_cap"]["display"] == "₹2,000.00"


async def test_order_status_is_readable(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    created = await call("create_order", {"product_id": "prd-cable"})
    env = await call("get_order_status", {"order_id": created["data"]["order_id"]})
    assert env["ok"] is True
    assert env["data"]["order"]["status"] == OrderStatus.AWAITING_PAYMENT.value


async def test_an_unknown_order_is_an_envelope_not_a_crash(
    db_session: AsyncSession,
) -> None:
    env = await call("get_order_status", {"order_id": "ord-nope"})
    assert env["ok"] is False
    assert env["error"]["code"] == "order_not_found"


# --------------------------------------------------------------------------
# The guardrails do not care which protocol the caller used
# --------------------------------------------------------------------------


async def test_a_small_order_executes(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    env = await call("create_order", {"product_id": "prd-cable"})
    assert env["ok"] is True
    assert env["data"]["status"] == OrderStatus.AWAITING_PAYMENT.value
    assert fake_razorpay.created[0]["amount_minor"] == 34_900


async def test_an_order_over_the_threshold_is_held_for_a_human(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    env = await call("create_order", {"product_id": "prd-mouse"})
    assert env["ok"] is True
    assert env["data"]["approval_required"] is True
    assert env["data"]["status"] == OrderStatus.PENDING_APPROVAL.value
    assert fake_razorpay.created == []  # nothing charged while it waits


async def test_an_order_over_the_hard_cap_is_refused(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    env = await call("create_order", {"product_id": "prd-headphones"})
    assert env["ok"] is False
    assert env["error"]["code"] == "spend_blocked"
    assert fake_razorpay.created == []  # the provider was never contacted


async def test_a_refusal_explains_which_bound_stopped_it(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """An external agent needs the reason, not just a rejection."""
    env = await call("create_order", {"product_id": "prd-headphones"})
    guardrail = env["error"]["details"]["guardrail"]
    failed = [c["name"] for c in guardrail["checks"] if not c["passed"]]
    assert failed[0] == "per_transaction_cap"


# --------------------------------------------------------------------------
# The audit trail records MCP calls like any other
# --------------------------------------------------------------------------


async def test_mcp_orders_are_audited_and_attributable(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    await call("create_order", {"product_id": "prd-cable"})

    entries = list(
        (
            await db_session.execute(
                # Money actions only: the fixture seeds a consent grant, which
                # shares this table by design.
                select(AuditLog).where(AuditLog.action == AuditAction.CREATE_ORDER)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].decision is AuditDecision.ALLOW
    # Attributable to MCP, so the dashboard can tell an external agent's
    # purchases from the in-app chat's.
    assert entries[0].conversation_id.startswith(MCP_CONVERSATION_PREFIX)


async def test_a_blocked_mcp_order_is_recorded_too(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    await call("create_order", {"product_id": "prd-headphones"})

    entries = list(
        (
            await db_session.execute(
                # Money actions only: the fixture seeds a consent grant, which
                # shares this table by design.
                select(AuditLog).where(AuditLog.action == AuditAction.CREATE_ORDER)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].decision is AuditDecision.BLOCK

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert orders[0].status is OrderStatus.BLOCKED


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


async def test_a_repeated_key_returns_the_original_order(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    first = await call("create_order", {"product_id": "prd-cable", "idempotency_key": "k-mcp"})
    second = await call("create_order", {"product_id": "prd-cable", "idempotency_key": "k-mcp"})

    assert second["data"]["idempotent_replay"] is True
    assert second["data"]["order_id"] == first["data"]["order_id"]
    assert len(fake_razorpay.created) == 1


async def test_calls_without_a_key_are_distinct_purchases(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """Two deliberate buys must not silently collapse into one."""
    a = await call("create_order", {"product_id": "prd-cable"})
    b = await call("create_order", {"product_id": "prd-cable"})

    assert a["data"]["order_id"] != b["data"]["order_id"]
    assert len(fake_razorpay.created) == 2
