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
