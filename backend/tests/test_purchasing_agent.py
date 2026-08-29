"""Purchasing agent graph tests.

The whole state machine is exercised with a scripted model — every branch,
including both money paths — with no API key, no network, and no spend.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import LLMUnavailable
from app.agents.purchasing_agent import AgentDeps, run_turn
from app.config import settings
from app.db.models import Order, OrderStatus
from tests.fakes import FakeRazorpay, ScriptedLLM, response, text_block, tool_use_block

pytestmark = pytest.mark.asyncio


async def collect(
    db_session: AsyncSession,
    llm: ScriptedLLM,
    message: str,
    *,
    history: list[dict[str, Any]] | None = None,
    conversation_id: str = "conv-test",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run a turn and return (events, final state event)."""
    deps = AgentDeps(session=db_session, llm=llm, conversation_id=conversation_id)
    messages = [*(history or []), {"role": "user", "content": message}]

    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    async for event in run_turn(deps, messages):
        if event["type"] == "state":
            state = event
        else:
            events.append(event)
    return events, state


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def first(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """First event of a kind.

    Raises AssertionError rather than StopIteration: inside an async test a bare
    StopIteration surfaces as an opaque "coroutine raised StopIteration" with no
    hint of which event was missing.
    """
    for event in events:
        if event["type"] == kind:
            return event
    raise AssertionError(
        f"no {kind!r} event; got {[e['type'] for e in events]}"
    )


# --------------------------------------------------------------------------
# Intent parsing
# --------------------------------------------------------------------------


async def test_intent_is_classified_and_emitted(db_session: AsyncSession) -> None:
    llm = ScriptedLLM(intents=["purchase"], turns=[response(text_block("ok"))])
    events, state = await collect(db_session, llm, "buy the mouse")

    assert first(events, "intent")["intent"] == "purchase"
    assert state["intent"] == "purchase"


async def test_an_unrecognised_intent_label_falls_back(db_session: AsyncSession) -> None:
    """A bad classification must not block the turn."""
    llm = ScriptedLLM(intents=["nonsense-label"], turns=[response(text_block("ok"))])
    _, state = await collect(db_session, llm, "hello")
    assert state["intent"] == "browse"


async def test_intent_classification_uses_a_cheap_call(db_session: AsyncSession) -> None:
    """Classification should not carry the tool list or a large token budget."""
    llm = ScriptedLLM(intents=["browse"], turns=[response(text_block("ok"))])
    await collect(db_session, llm, "show me mice")

    classification = llm.calls[0]
    assert classification["tools"] == []
    assert classification["max_tokens"] == 16
    assert classification["effort"] == "low"


# --------------------------------------------------------------------------
# Catalog path
# --------------------------------------------------------------------------


async def test_catalog_search_flows_through_to_a_product_event(
    db_session: AsyncSession,
) -> None:
    llm = ScriptedLLM(
        intents=["browse"],
        turns=[
            response(
                text_block("Looking."),
                tool_use_block("t1", "search_catalog", {"query": "mouse"}),
            ),
            response(text_block("The Silent Wireless Mouse is ₹1,299.00.")),
        ],
    )
    events, state = await collect(db_session, llm, "I need a mouse")

    assert kinds(events) == [
        "intent",
        "message",
        "tool_call",
        "tool_result",
        "products",
        "message",
        "done",
    ]
    assert first(events, "tool_call")["mutates_money"] is False
    assert [p["id"] for p in first(events, "products")["products"]] == ["prd-mouse"]
    assert state["error"] is None


async def test_tool_results_are_batched_into_one_user_message(
    db_session: AsyncSession,
) -> None:
    """Splitting results across messages trains the model out of parallel calls."""
    llm = ScriptedLLM(
        intents=["browse"],
        turns=[
            response(
                tool_use_block("t1", "search_catalog", {"query": "mouse"}),
                tool_use_block("t2", "get_product", {"product_id": "prd-cable"}),
            ),
            response(text_block("Here are two options.")),
        ],
    )
    _, state = await collect(db_session, llm, "options please")

    tool_result_messages = [
        m
        for m in state["messages"]
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2


# --------------------------------------------------------------------------
# Money path
# --------------------------------------------------------------------------


async def test_create_order_routes_through_the_money_node(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay, generous_limits: None) -> None:
    llm = ScriptedLLM(
        intents=["purchase"],
        turns=[
            response(
                text_block("Ordering."),
                tool_use_block("t1", "create_order", {"product_id": "prd-mouse", "quantity": 1}),
            ),
            response(text_block("Order created. Please pay ₹1,299.00.")),
        ],
    )
    events, _ = await collect(db_session, llm, "buy the mouse")

    call = first(events, "tool_call")
    assert call["tool"] == "create_order"
    assert call["mutates_money"] is True

    order = first(events, "order")["order"]
    assert order["status"] == OrderStatus.AWAITING_PAYMENT.value
    assert order["total"]["amount_minor"] == 129_900
    assert fake_razorpay.created[0]["amount_minor"] == 129_900


async def test_the_agent_not_the_model_sets_the_conversation_id(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay, generous_limits: None) -> None:
    """Otherwise a prompt injection could attribute an order to another thread."""
    llm = ScriptedLLM(
        intents=["purchase"],
        turns=[
            response(
                tool_use_block(
                    "t1",
                    "create_order",
                    # The model tries to supply someone else's conversation.
                    {"product_id": "prd-mouse", "quantity": 1, "conversation_id": "conv-victim"},
                )
            ),
            response(text_block("done")),
        ],
    )
    events, _ = await collect(
        db_session, llm, "buy it", conversation_id="conv-mine"
    )

    order_id = first(events, "order")["order"]["order_id"]
    order = await db_session.get(Order, order_id)
    assert order is not None
    assert order.conversation_id == "conv-mine"


async def test_payment_verification_settles_the_order(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay, generous_limits: None) -> None:
    llm = ScriptedLLM(
        intents=["purchase", "verify"],
        turns=[
            response(tool_use_block("t1", "create_order", {"product_id": "prd-mouse"})),
            response(text_block("Please pay.")),
        ],
    )
    events, state = await collect(db_session, llm, "buy the mouse")
    rzp_order_id = first(events, "order")["order"]["razorpay_order_id"]

    llm._turns = [
        response(
            tool_use_block(
                "t2",
                "verify_payment",
                {
                    "razorpay_order_id": rzp_order_id,
                    "razorpay_payment_id": "pay_TEST1",
                    "razorpay_signature": "sig",
                },
            )
        ),
        response(text_block("Payment confirmed.")),
    ]
    events2, _ = await collect(
        db_session, llm, "I've paid", history=state["messages"]
    )

    settled = first(events2, "order")["order"]
    assert settled["status"] == OrderStatus.PAID.value
    assert fake_razorpay.verified[0]["payment_id"] == "pay_TEST1"


# --------------------------------------------------------------------------
# Failure handling — the turn must degrade, never die
# --------------------------------------------------------------------------


async def test_a_failing_tool_becomes_an_error_result_the_model_can_read(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    llm = ScriptedLLM(
        intents=["purchase"],
        turns=[
            response(
                tool_use_block("t1", "create_order", {"product_id": "prd-espresso"})
            ),
            response(text_block("That one is out of stock.")),
        ],
    )
    events, state = await collect(db_session, llm, "buy the espresso machine")

    result = first(events, "tool_result")
    assert result["ok"] is False
    assert result["error"]["code"] == "insufficient_stock"

    # The failure reaches the model flagged as an error, not as a success.
    tool_result_block = next(
        b
        for m in state["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    )
    assert tool_result_block["is_error"] is True
    assert state["error"] is None  # the turn itself completed


async def test_an_unknown_tool_does_not_kill_the_turn(
    db_session: AsyncSession,
) -> None:
    llm = ScriptedLLM(
        intents=["browse"],
        turns=[
            response(tool_use_block("t1", "drop_tables", {})),
            response(text_block("I can't do that.")),
        ],
    )
    events, state = await collect(db_session, llm, "delete everything")

    assert first(events, "tool_result")["error"]["code"] == "unknown_tool"
    assert first(events, "done")["text"] == "I can't do that."


async def test_model_unavailable_stops_cleanly_without_guessing(
    db_session: AsyncSession,
) -> None:
    llm = ScriptedLLM(fail_with=LLMUnavailable("upstream down", retryable=True))
    events, state = await collect(db_session, llm, "buy something")

    assert state["error"]["code"] == "llm_unavailable"
    assert state["error"]["retryable"] is True
    # It says so rather than fabricating a purchase.
    assert "stopped" in first(events, "done")["text"]


async def test_the_tool_loop_is_bounded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that keeps calling tools must terminate, not spin forever."""
    monkeypatch.setattr(settings, "agent_max_iterations", 3)

    llm = ScriptedLLM(
        intents=["browse"],
        turns=[
            response(tool_use_block(f"t{i}", "search_catalog", {"query": "mouse"}))
            for i in range(10)
        ],
    )
    _, state = await collect(db_session, llm, "loop forever")

    assert state["error"]["code"] == "max_iterations"
    # Stopped at the ceiling rather than consuming the whole script.
    assert llm.turns_remaining == 7
