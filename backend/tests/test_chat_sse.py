"""`POST /chat` Server-Sent Events tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Conversation
from tests.fakes import FakeRazorpay, ScriptedLLM, response, text_block, tool_use_block

pytestmark = pytest.mark.asyncio


async def sse(client: AsyncClient, **body: Any) -> list[tuple[str, dict[str, Any]]]:
    """POST to /chat and parse the event stream into (event, data) pairs."""
    frames: list[tuple[str, dict[str, Any]]] = []
    event = "message"

    async with client.stream("POST", "/chat", json=body) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        async for raw in resp.aiter_lines():
            line = raw.rstrip("\r")
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    frames.append((event, json.loads(payload)))
    return frames


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> ScriptedLLM:
    """Wire a scripted model into the chat endpoint and mark the key present."""
    import app.api.chat as chat_module

    llm = ScriptedLLM()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(chat_module, "get_agent_client", lambda: llm)
    return llm


def names(frames: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in frames]


def payload(frames: list[tuple[str, dict[str, Any]]], name: str) -> dict[str, Any]:
    return next(data for event, data in frames if event == name)


# --------------------------------------------------------------------------


async def test_a_turn_streams_a_conversation_id_first(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    agent._turns = [response(text_block("Hello."))]
    frames = await sse(client, message="hi")

    assert names(frames)[0] == "conversation"
    assert payload(frames, "conversation")["conversation_id"].startswith("conv-")
    assert names(frames)[-1] == "end"


async def test_the_agents_reply_is_streamed(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    agent._turns = [response(text_block("We have three mice."))]
    frames = await sse(client, message="show me mice")

    assert payload(frames, "message")["text"] == "We have three mice."
    assert payload(frames, "done")["text"] == "We have three mice."


async def test_product_results_are_streamed_as_structured_events(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    agent._turns = [
        response(tool_use_block("t1", "search_catalog", {"query": "mouse"})),
        response(text_block("Found one.")),
    ]
    frames = await sse(client, message="find a mouse")

    assert "products" in names(frames)
    assert [p["id"] for p in payload(frames, "products")["products"]] == ["prd-mouse"]


async def test_an_order_is_streamed_as_a_structured_event(
    client: AsyncClient, agent: ScriptedLLM, fake_razorpay: FakeRazorpay
) -> None:
    agent._turns = [
        response(tool_use_block("t1", "create_order", {"product_id": "prd-cable"})),
        response(text_block("Ordered.")),
    ]
    frames = await sse(client, message="buy the cable")

    order = payload(frames, "order")["order"]
    assert order["total"]["display"] == "₹349.00"
    assert order["status"] == "awaiting_payment"


async def test_the_transcript_persists_across_requests(
    client: AsyncClient, agent: ScriptedLLM, db_session: AsyncSession
) -> None:
    agent._turns = [response(text_block("Hello."))]
    first = await sse(client, message="hi")
    conversation_id = payload(first, "conversation")["conversation_id"]

    agent._turns = [response(text_block("Still here."))]
    second = await sse(client, message="are you there?", conversation_id=conversation_id)

    assert payload(second, "conversation")["conversation_id"] == conversation_id

    stored = await db_session.get(Conversation, conversation_id)
    assert stored is not None
    # Two user turns plus two assistant replies.
    assert len(stored.messages) == 4
    assert stored.messages[0]["content"] == "hi"
    assert stored.messages[2]["content"] == "are you there?"


async def test_the_stream_never_leaks_the_raw_transcript(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    """`state` carries thinking blocks and full history; it must stay server-side."""
    agent._turns = [response(text_block("Hi."))]
    frames = await sse(client, message="hi")
    assert "state" not in names(frames)


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


async def test_a_missing_api_key_is_a_streamed_error_not_a_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    frames = await sse(client, message="hi")

    assert payload(frames, "error")["code"] == "llm_not_configured"
    assert "done" not in names(frames)


async def test_a_tool_failure_is_reported_not_hidden(
    client: AsyncClient, agent: ScriptedLLM, fake_razorpay: FakeRazorpay
) -> None:
    agent._turns = [
        response(tool_use_block("t1", "create_order", {"product_id": "prd-espresso"})),
        response(text_block("That's out of stock.")),
    ]
    frames = await sse(client, message="buy the espresso machine")

    result = payload(frames, "tool_result")
    assert result["ok"] is False
    assert result["error"]["code"] == "insufficient_stock"
    assert payload(frames, "done")["text"] == "That's out of stock."


async def test_an_empty_message_is_rejected_before_streaming(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    assert (await client.post("/chat", json={"message": ""})).status_code == 422


async def test_an_overlong_message_is_rejected(
    client: AsyncClient, agent: ScriptedLLM
) -> None:
    resp = await client.post("/chat", json={"message": "x" * 5000})
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# The guardrail and approval gate, end to end
# --------------------------------------------------------------------------


async def test_the_approval_gate_reaches_the_browser(
    client: AsyncClient, agent: ScriptedLLM, fake_razorpay: FakeRazorpay
) -> None:
    """End to end: a gated order must stream both the guardrail and the prompt."""
    agent._turns = [
        response(tool_use_block("t1", "create_order", {"product_id": "prd-mouse"})),
        response(text_block("That needs your approval.")),
    ]
    frames = await sse(client, message="buy the mouse")

    assert "guardrail" in names(frames)
    assert "approval_required" in names(frames)

    guardrail = payload(frames, "guardrail")
    assert guardrail["blocked"] is False
    assert {c["name"] for c in guardrail["checks"]} == {
        "agent_authority",
        "per_transaction_cap",
        "daily_cap",
        "auto_approve_limit",
    }

    approval = payload(frames, "approval_required")
    assert approval["total"]["display"] == "₹1,299.00"
    assert approval["order_id"].startswith("ord-")


async def test_a_blocked_order_streams_the_bound_that_stopped_it(
    client: AsyncClient, agent: ScriptedLLM, fake_razorpay: FakeRazorpay
) -> None:
    agent._turns = [
        response(tool_use_block("t1", "create_order", {"product_id": "prd-headphones"})),
        response(text_block("I can't buy that.")),
    ]
    frames = await sse(client, message="buy the headphones")

    guardrail = payload(frames, "guardrail")
    assert guardrail["blocked"] is True
    failed = [c["name"] for c in guardrail["checks"] if not c["passed"]]
    assert failed[0] == "per_transaction_cap"
    # A refusal is not an approval prompt — there is nothing to approve.
    assert "approval_required" not in names(frames)
