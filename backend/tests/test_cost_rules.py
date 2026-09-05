"""Graph-level tests for the cost-reduction rules: intent classification is
routed to the cheap model, and unambiguous replies skip the model entirely.

These run the real `purchasing_agent` graph — the same one `/chat` drives —
against the `ScriptedLLM` test double, so they check what the graph actually
sends, not a description of it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.purchasing_agent import AgentDeps, run_turn
from app.config import settings
from app.services import llm_usage
from tests.fakes import FakeRazorpay, ScriptedLLM, response, text_block, tool_use_block

pytestmark = pytest.mark.asyncio


async def collect(
    db_session: AsyncSession, llm: ScriptedLLM, message: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    deps = AgentDeps(session=db_session, llm=llm, conversation_id="conv-cost")
    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    async for event in run_turn(deps, [{"role": "user", "content": message}]):
        (state.update(event) if event["type"] == "state" else events.append(event))
    return events, state


def first(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    for e in events:
        if e["type"] == kind:
            return e
    raise AssertionError(f"no {kind!r} event; got {[e['type'] for e in events]}")


# --------------------------------------------------------------------------
# Intent classification goes to the cheap model; the buyer-facing call doesn't
# --------------------------------------------------------------------------


async def test_intent_classification_is_routed_to_the_intent_model(
    db_session: AsyncSession,
) -> None:
    """A 5-way label that never gates money has no business on the model the
    buyer is talking to. `parse_intent` is always the first call in a turn."""
    llm = ScriptedLLM(intents=["browse"], turns=[response(text_block("hi"))])
    await collect(db_session, llm, "show me a mouse")

    intent_call = llm.calls[0]
    assert intent_call["model"] == settings.anthropic_intent_model
    assert intent_call["purpose"] == "intent"


async def test_the_buyer_facing_call_keeps_the_default_model(
    db_session: AsyncSession,
) -> None:
    """The cost rules must land only on the classification call — the call
    that produces what the buyer reads keeps its full model and quality."""
    llm = ScriptedLLM(intents=["browse"], turns=[response(text_block("hi"))])
    await collect(db_session, llm, "show me a mouse")

    agent_call = llm.calls[1]
    assert agent_call["model"] is None  # no override -> the configured default
    assert agent_call["purpose"] == "agent"


# --------------------------------------------------------------------------
# Unambiguous replies never reach the model at all
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected_intent"),
    [
        ("yes", "purchase"),
        ("Yes", "purchase"),
        ("  yep  ", "purchase"),
        ("approve", "purchase"),
        ("no", "cancel"),
        ("cancel", "cancel"),
        ("never mind", "cancel"),
    ],
)
async def test_unambiguous_replies_skip_the_classifier(
    db_session: AsyncSession, reply: str, expected_intent: str
) -> None:
    """These carry no second reading, so recognising them without a network
    round trip does not trade away classification quality — there is no gap
    to close. A comparable non-shortcut turn makes 2 calls (intent, agent);
    this makes 1 (agent only)."""
    llm = ScriptedLLM(turns=[response(text_block("ok"))])
    events, state = await collect(db_session, llm, reply)

    assert len(llm.calls) == 1, "the intent call must not have happened"
    assert llm.calls[0]["purpose"] == "agent"
    assert state["intent"] == expected_intent


async def test_unambiguous_replies_still_emit_the_intent_event(
    db_session: AsyncSession,
) -> None:
    """Skipping the model call must not remove the UI's intent badge — the
    buyer sees the same label either way, it is just computed for free."""
    llm = ScriptedLLM(turns=[response(text_block("ok"))])
    events, _ = await collect(db_session, llm, "yes")

    assert first(events, "intent")["intent"] == "purchase"


async def test_unambiguous_shortcut_is_reflected_in_the_usage_report(
    db_session: AsyncSession,
) -> None:
    llm = ScriptedLLM(turns=[response(text_block("ok"))])
    await collect(db_session, llm, "yes")

    snap = llm_usage.snapshot()
    assert snap["savings"]["from_short_circuited_intents"]["count"] == 1


async def test_an_ambiguous_reply_containing_a_shortcut_word_is_not_shortcut(
    db_session: AsyncSession,
) -> None:
    """"yes but not the headphones" is not unambiguous — it must still reach
    the classifier rather than being misread as a bare approval."""
    llm = ScriptedLLM(
        intents=["purchase"], turns=[response(text_block("Got it."))]
    )
    events, _ = await collect(
        db_session, llm, "yes but not the noise cancelling ones"
    )

    assert len(llm.calls) == 2, "the intent call must still have happened"
    assert llm.calls[0]["purpose"] == "intent"
