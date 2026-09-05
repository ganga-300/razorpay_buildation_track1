"""Scripted planner tests.

The planner is a stand-in for the model, so what matters is not that it is
clever but that it drives the graph correctly — and, above all, that swapping
it in changes **nothing** about the guardrails, the gate, or the audit trail.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import get_agent_client
from app.agents.purchasing_agent import AgentDeps, run_turn
from app.agents.scripted_planner import ScriptedPlanner, _price_ceiling
from app.config import settings
from app.db.models import AuditAction, AuditDecision, AuditLog, AuditOutcome, OrderStatus
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


async def drive(
    db_session: AsyncSession, message: str, history=None
) -> tuple[list[dict], dict]:
    deps = AgentDeps(
        session=db_session, llm=ScriptedPlanner(), conversation_id="conv-scripted"
    )
    messages = [*(history or []), {"role": "user", "content": message}]
    events, state = [], {}
    async for e in run_turn(deps, messages):
        (state.update(e) if e["type"] == "state" else events.append(e))
    return events, state


def kinds(events):
    return [e["type"] for e in events]


def first(events, kind):
    for e in events:
        if e["type"] == kind:
            return e
    raise AssertionError(f"no {kind!r} event; got {kinds(events)}")


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Driving the graph
# --------------------------------------------------------------------------


async def test_browsing_searches_the_catalog(db_session: AsyncSession) -> None:
    events, _ = await drive(db_session, "I need a wireless mouse")

    assert first(events, "tool_call")["tool"] == "search_catalog"
    assert [p["id"] for p in first(events, "products")["products"]]
    assert "mouse" in first(events, "done")["text"].lower()


async def test_a_price_ceiling_becomes_a_filter(db_session: AsyncSession) -> None:
    events, _ = await drive(db_session, "I need a cable under 500")
    assert first(events, "tool_call")["arguments"]["max_price_minor"] == 50_000


async def test_buying_something_already_shown_orders_it(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    _, state = await drive(db_session, "show me a usb-c cable")
    events, _ = await drive(db_session, "buy the cable", history=state["messages"])

    call = first(events, "tool_call")
    assert call["tool"] == "create_order"
    assert call["mutates_money"] is True
    assert first(events, "order")["order"]["status"] == OrderStatus.AWAITING_PAYMENT.value


async def test_cancelling_orders_nothing(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    events, _ = await drive(db_session, "never mind, cancel that")
    assert "tool_call" not in kinds(events)
    assert fake_razorpay.created == []


# --------------------------------------------------------------------------
# The safety properties do not depend on the model
# --------------------------------------------------------------------------


async def test_the_approval_gate_still_fires(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    _, state = await drive(db_session, "show me a wireless mouse")
    events, _ = await drive(db_session, "buy the mouse", history=state["messages"])

    assert "approval_required" in kinds(events)
    assert first(events, "order")["order"]["status"] == OrderStatus.PENDING_APPROVAL.value
    assert fake_razorpay.created == []  # nothing charged while it waits


async def test_the_hard_cap_still_blocks(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    _, state = await drive(db_session, "show me noise cancelling headphones")
    events, _ = await drive(db_session, "buy the headphones", history=state["messages"])

    guardrail = first(events, "guardrail")
    assert guardrail["blocked"] is True
    assert fake_razorpay.created == []
    assert "merchant limit" in first(events, "done")["text"]


async def test_the_audit_trail_is_written_the_same_way(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """The record must not be thinner just because a rule table drove the turn."""
    _, state = await drive(db_session, "show me noise cancelling headphones")
    await drive(db_session, "buy the headphones", history=state["messages"])

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
    entry = entries[0]
    assert entry.decision is AuditDecision.BLOCK
    assert entry.outcome is AuditOutcome.BLOCKED
    assert entry.agent_id == "purchasing-agent"
    assert {c["name"] for c in entry.checks} == {
        "agent_authority",
        "per_transaction_cap",
        "daily_cap",
        "auto_approve_limit",
    }


async def test_a_provider_failure_is_explained(
    db_session: AsyncSession,
    generous_limits: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import orders as orders_service
    from app.services.razorpay_client import RazorpayError

    failing = FakeRazorpay(
        fail_create=RazorpayError("provider_unavailable", "gateway down", retryable=True)
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: failing)

    _, state = await drive(db_session, "show me a usb-c cable")
    events, _ = await drive(db_session, "buy the cable", history=state["messages"])

    reply = first(events, "done")["text"]
    assert "retried once" in reply
    assert "Nothing was charged" in reply


# --------------------------------------------------------------------------
# The planner reaches every tool, not just the two it needs to buy
# --------------------------------------------------------------------------


async def test_the_planner_can_reach_every_registered_tool() -> None:
    """The chat agent should not be less capable than an external MCP client.

    `get_order_status` and `verify_payment` were exposed over MCP while the
    planner could never call them, so a buyer asking "did my payment go
    through?" in chat got nothing — while a stranger's agent could ask.
    """
    import re
    from pathlib import Path

    from app.agents import scripted_planner
    from app.tools import registry

    source = Path(scripted_planner.__file__).read_text()
    reachable = set(re.findall(r'_tool_block\([^,]+,\s*"([a-z_]+)"', source))

    missing = set(registry.names()) - reachable
    assert not missing, f"the planner can never call: {sorted(missing)}"


async def test_asking_about_an_order_checks_its_status(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    _, state = await drive(db_session, "show me a usb-c cable")
    _, state = await drive(db_session, "buy the cable", history=state["messages"])

    events, _ = await drive(
        db_session, "did my payment go through?", history=state["messages"]
    )

    call = first(events, "tool_call")
    assert call["tool"] == "get_order_status"
    assert call["mutates_money"] is False
    assert "awaiting payment" in first(events, "done")["text"].lower()


async def test_asking_before_ordering_says_so(db_session: AsyncSession) -> None:
    events, _ = await drive(db_session, "what's the status of my order?")
    assert "tool_call" not in kinds(events)
    assert "haven't placed an order" in first(events, "done")["text"]


async def test_pasted_checkout_values_trigger_verification(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """The one case where settling through chat makes sense."""
    _, state = await drive(db_session, "show me a usb-c cable")
    _, state = await drive(db_session, "buy the cable", history=state["messages"])

    rzp_order = fake_razorpay.issued_ids[0]
    signature = "a" * 64
    events, _ = await drive(
        db_session,
        f"paid: {rzp_order} pay_TESTPAYMENT01 {signature}",
        history=state["messages"],
    )

    call = first(events, "tool_call")
    assert call["tool"] == "verify_payment"
    assert call["mutates_money"] is True
    assert first(events, "order")["order"]["status"] == OrderStatus.PAID.value


async def test_incomplete_checkout_values_are_not_treated_as_a_verification(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """Verifying with a missing field is a failed verification, not a partial one."""
    events, _ = await drive(db_session, "I paid, the id was order_TX5W4A4ui4doy5")
    assert all(e.get("tool") != "verify_payment" for e in events)


async def test_an_exact_product_id_is_fetched_directly(
    db_session: AsyncSession,
) -> None:
    events, _ = await drive(db_session, "tell me about prd-mouse")
    call = first(events, "tool_call")
    assert call["tool"] == "get_product"
    assert call["arguments"]["product_id"] == "prd-mouse"


async def test_buying_by_exact_id_skips_the_search(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    events, _ = await drive(db_session, "buy prd-cable")
    call = first(events, "tool_call")
    assert call["tool"] == "create_order"
    assert call["arguments"]["product_id"] == "prd-cable"


async def test_razorpay_ids_survive_keyword_matching(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """Regression: the planner lowercased the whole message for matching.

    Razorpay identifiers are case-sensitive, so `order_TESTFAKE0001` arrived as
    `order_testfake0001` and every pasted verification failed with
    order_not_found — a path that could never have worked in production.
    """
    from app.agents.scripted_planner import _checkout_values

    values = _checkout_values(f"Paid! order_ABCdef123456 pay_XYZabc789012 {'a' * 64}")
    assert values is not None
    assert values["razorpay_order_id"] == "order_ABCdef123456"
    assert values["razorpay_payment_id"] == "pay_XYZabc789012"


# --------------------------------------------------------------------------
# The "which one?" loop
# --------------------------------------------------------------------------


async def test_naming_a_listed_product_orders_it(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """Regression: the agent asked "which one?" and ignored the answer.

    Replying with the product's name carries no verb, so intent alone read it as
    "browse" — the agent searched again, relisted the same item, and asked the
    same question. A buyer hits that loop on their first conversation.
    """
    _, state = await drive(db_session, "show me noise cancelling headphones")
    events, _ = await drive(
        db_session,
        "Wireless Noise Cancelling Headphones",
        history=state["messages"],
    )

    call = first(events, "tool_call")
    assert call["tool"] == "create_order"


async def test_asking_to_see_more_still_searches(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """The fix must not turn every browse into a purchase."""
    _, state = await drive(db_session, "show me a usb-c cable")

    for phrase in (
        "show me something else",
        "what other cables do you have",
        "any cheaper options",
    ):
        events, _ = await drive(db_session, phrase, history=state["messages"])
        assert first(events, "tool_call")["tool"] == "search_catalog", phrase


async def test_naming_something_never_shown_still_searches(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """With nothing listed yet, a bare product name is a search, not an order."""
    events, _ = await drive(db_session, "wireless mouse")
    assert first(events, "tool_call")["tool"] == "search_catalog"
