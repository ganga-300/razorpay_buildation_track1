"""The LangGraph purchasing agent.

The graph is deliberately explicit rather than a single generic tool loop:

    START -> parse_intent -> agent -> [dispatch] -> search_catalog
                              ^                  -> create_order      (money)
                              |                  -> verify_payment    (money)
                              |                        |
                              +---- collect_results <--+
                              |
                              +-> finish -> END

Money-moving tools get their **own named nodes**. That is the point. A generic
"execute whatever the model asked for" node would make the spend gate a
conditional buried inside an executor; separate nodes make it a structural
property of the graph, so the guardrail in Milestone 4 has exactly one place to
live and cannot be bypassed by a tool being routed elsewhere.

Two bounds hold regardless of what the model does:

* `agent_max_iterations` caps tool-calling rounds per turn, so a model that
  keeps calling tools terminates instead of spinning.
* Every tool result is an envelope, never an exception, so one failing tool
  degrades the answer rather than killing the turn.
"""

from __future__ import annotations

import logging
import operator
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import LLMClient, LLMResponse, LLMUnavailable, ToolCall
from app.agents.prompts import (
    DEFAULT_INTENT,
    INTENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    VALID_INTENTS,
)
from app.config import settings
from app.tools import execute_tool, registry

logger = logging.getLogger(__name__)

# Which node handles which tool. Adding a money tool without adding it here
# raises at graph-build time rather than silently routing to the catalog node.
TOOL_PHASES: dict[str, str] = {
    "search_catalog": "search_catalog",
    "get_product": "search_catalog",
    "create_order": "create_order",
    "verify_payment": "verify_payment",
}

PHASE_NODES = ("search_catalog", "create_order", "verify_payment")

# Every event type `run_turn` can emit. The SSE layer derives what it forwards
# from this set, so adding an event in one place and forgetting the other is not
# possible — a new type registered here reaches the browser automatically, and
# one that is emitted but never registered fails `test_every_emitted_event_is_registered`.
AGENT_EVENT_TYPES = frozenset(
    {
        "intent",
        "message",
        "tool_call",
        "tool_result",
        "products",
        "order",
        "guardrail",
        "approval_required",
        "done",
        "state",
    }
)

# Never forwarded to the browser: `state` carries the full transcript, including
# thinking blocks, which the UI has no use for.
INTERNAL_EVENT_TYPES = frozenset({"state"})


class AgentState(TypedDict, total=False):
    """State threaded through the graph for one chat turn."""

    conversation_id: str
    messages: list[dict[str, Any]]
    intent: str
    pending_calls: list[ToolCall]
    tool_results: list[dict[str, Any]]
    # Reducer, not replacement: nodes return only the events they produced and
    # LangGraph concatenates them, so the streaming layer can emit each node's
    # events the moment that node finishes.
    events: Annotated[list[dict[str, Any]], operator.add]
    iterations: int
    final_text: str
    error: dict[str, Any] | None


@dataclass
class AgentDeps:
    """Runtime dependencies. Injected per request so tests can substitute fakes."""

    session: AsyncSession
    llm: LLMClient
    conversation_id: str


def _event(kind: str, **payload: Any) -> dict[str, Any]:
    return {"type": kind, **payload}


def phase_for(tool_name: str) -> str:
    """Node that owns a tool. Unknown tools go to the catalog node, whose
    executor returns an `unknown_tool` envelope the model can recover from."""
    return TOOL_PHASES.get(tool_name, "search_catalog")


def _validate_tool_coverage() -> None:
    """Every registered tool must be routed, and every money tool must land on a
    money node. Enforced at import so a mis-registered tool fails loudly."""
    for name in registry.names():
        if name not in TOOL_PHASES:
            raise RuntimeError(
                f"Tool {name!r} is registered but has no node in TOOL_PHASES. "
                "Add it before it can be called."
            )
    for name in registry.money_tools():
        if TOOL_PHASES[name] not in {"create_order", "verify_payment"}:
            raise RuntimeError(
                f"Money tool {name!r} is routed to {TOOL_PHASES[name]!r}, which is "
                "not a gated node. Money must not flow through the catalog path."
            )


def build_graph(deps: AgentDeps) -> Any:
    """Compile the purchasing graph bound to one request's dependencies."""

    # ---- nodes ---------------------------------------------------------

    async def parse_intent(state: AgentState) -> dict[str, Any]:
        """Classify the turn.

        Recorded for explainability — it is what the agent believed the buyer
        wanted, which is worth having next to the money decisions in the audit
        trail. It never gates behaviour: a failed classification falls back to a
        default rather than blocking the turn.
        """
        latest = _latest_user_text(state.get("messages", []))
        if not latest:
            return {"intent": DEFAULT_INTENT}

        try:
            response = await deps.llm.complete(
                system=INTENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": latest}],
                max_tokens=16,
                effort="low",
            )
            label = response.text.strip().lower().split()[0] if response.text.strip() else ""
        except (LLMUnavailable, IndexError) as exc:
            logger.info("Intent classification unavailable, defaulting: %s", exc)
            label = ""

        intent = label if label in VALID_INTENTS else DEFAULT_INTENT
        return {
            "intent": intent,
            "events": [_event("intent", intent=intent)],
        }

    async def agent(state: AgentState) -> dict[str, Any]:
        """Ask the model what to do next."""
        iterations = state.get("iterations", 0)

        if iterations >= settings.agent_max_iterations:
            logger.warning(
                "Agent hit the %s-iteration ceiling", settings.agent_max_iterations
            )
            return {
                "pending_calls": [],
                "final_text": (
                    "I wasn't able to finish that in a reasonable number of steps. "
                    "Could you restate what you'd like to buy?"
                ),
                "error": {
                    "code": "max_iterations",
                    "message": f"Exceeded {settings.agent_max_iterations} tool rounds.",
                },
            }

        try:
            response = await deps.llm.complete(
                system=SYSTEM_PROMPT,
                messages=state["messages"],
                tools=registry.to_anthropic(),
            )
        except LLMUnavailable as exc:
            return {
                "pending_calls": [],
                "final_text": (
                    "I can't reach my reasoning model right now, so I've stopped "
                    "rather than guess about a purchase. Please try again shortly."
                ),
                "error": {
                    "code": "llm_unavailable",
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
            }

        return _apply_response(state, response, iterations)

    def _apply_response(
        state: AgentState, response: LLMResponse, iterations: int
    ) -> dict[str, Any]:
        messages = [*state["messages"], {"role": "assistant", "content": response.content}]
        events: list[dict[str, Any]] = []

        if response.text:
            events.append(_event("message", text=response.text))
        for call in response.tool_calls:
            events.append(
                _event(
                    "tool_call",
                    tool=call.name,
                    arguments=call.arguments,
                    mutates_money=call.name in registry.money_tools(),
                )
            )

        return {
            "messages": messages,
            "pending_calls": list(response.tool_calls),
            "iterations": iterations + 1,
            "final_text": response.text,
            "events": events,
        }

    def _make_tool_node(phase: str):
        """Build a node that executes exactly the pending calls it owns."""

        async def node(state: AgentState) -> dict[str, Any]:
            pending = state.get("pending_calls", [])
            mine = [c for c in pending if phase_for(c.name) == phase]
            rest = [c for c in pending if phase_for(c.name) != phase]

            results = list(state.get("tool_results", []))
            events: list[dict[str, Any]] = []

            for call in mine:
                arguments = dict(call.arguments)

                # The agent, not the model, decides which conversation an order
                # belongs to. Letting the model supply this would let a prompt
                # injection attribute an order to someone else's thread.
                if call.name == "create_order":
                    arguments["conversation_id"] = deps.conversation_id
                    # Derived from the model's own tool_use id, so an internal
                    # retry of this exact call reuses the key and cannot produce
                    # a second charge, while a genuine second purchase gets a
                    # new id and proceeds normally.
                    arguments["idempotency_key"] = f"{deps.conversation_id}:{call.id}"

                envelope = await execute_tool(call.name, deps.session, arguments)

                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": _as_tool_content(envelope),
                        **({"is_error": True} if not envelope.get("ok") else {}),
                    }
                )
                events.append(
                    _event(
                        "tool_result",
                        tool=call.name,
                        ok=bool(envelope.get("ok")),
                        error=envelope.get("error"),
                    )
                )
                events.extend(_domain_events(call.name, envelope))

            return {"pending_calls": rest, "tool_results": results, "events": events}

        return node

    async def collect_results(state: AgentState) -> dict[str, Any]:
        """Append every tool result as ONE user message.

        The API requires all results for an assistant turn in a single message.
        Splitting them across messages trains the model to stop making parallel
        tool calls, so this batching step is not optional.
        """
        results = state.get("tool_results", [])
        if not results:
            return {"tool_results": []}

        return {
            "messages": [*state["messages"], {"role": "user", "content": results}],
            "tool_results": [],
        }

    async def finish(state: AgentState) -> dict[str, Any]:
        text = state.get("final_text") or ""
        return {"events": [_event("done", text=text, intent=state.get("intent"))]}

    # ---- routing -------------------------------------------------------

    def route_from_agent(state: AgentState) -> str:
        pending = state.get("pending_calls", [])
        if not pending:
            return "finish"
        return phase_for(pending[0].name)

    def route_after_tools(state: AgentState) -> str:
        pending = state.get("pending_calls", [])
        if pending:
            return phase_for(pending[0].name)
        return "collect_results"

    # ---- assembly ------------------------------------------------------

    graph = StateGraph(AgentState)
    graph.add_node("parse_intent", parse_intent)
    graph.add_node("agent", agent)
    for phase in PHASE_NODES:
        graph.add_node(phase, _make_tool_node(phase))
    graph.add_node("collect_results", collect_results)
    graph.add_node("finish", finish)

    graph.add_edge(START, "parse_intent")
    graph.add_edge("parse_intent", "agent")

    graph.add_conditional_edges(
        "agent",
        route_from_agent,
        {**{p: p for p in PHASE_NODES}, "finish": "finish"},
    )
    for phase in PHASE_NODES:
        graph.add_conditional_edges(
            phase,
            route_after_tools,
            {**{p: p for p in PHASE_NODES}, "collect_results": "collect_results"},
        )

    graph.add_edge("collect_results", "agent")
    graph.add_edge("finish", END)

    return graph.compile()


# ---- helpers -----------------------------------------------------------


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Text of the most recent user turn, ignoring tool-result messages."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text = "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if text:
                return text
    return ""


def _as_tool_content(envelope: dict[str, Any]) -> str:
    """Render a tool envelope as the string content of a tool_result block."""
    import json

    return json.dumps(envelope, ensure_ascii=False, default=str)


def _domain_events(tool_name: str, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured events the UI renders as cards rather than as text."""
    if not envelope.get("ok"):
        # A refusal is as much a result as a purchase. When the guardrails
        # blocked the action, the bounds that were checked travel to the UI so
        # the buyer sees *which* limit stopped it, not just that something did.
        error = envelope.get("error") or {}
        guardrail = (error.get("details") or {}).get("guardrail")
        if guardrail:
            return [_event("guardrail", **guardrail, blocked=True)]
        return []

    data = envelope.get("data") or {}
    if tool_name == "search_catalog":
        products = data.get("products") or []
        return [_event("products", products=products[:3])] if products else []
    if tool_name == "get_product":
        product = data.get("product")
        return [_event("products", products=[product])] if product else []
    if tool_name in {"create_order", "verify_payment"}:
        events: list[dict[str, Any]] = []
        if data.get("guardrail"):
            events.append(_event("guardrail", **data["guardrail"], blocked=False))
        events.append(_event("order", order=data))
        if data.get("approval_required"):
            # The UI renders an explicit Approve/Decline control. Approval is
            # never inferred from the buyer typing "yes" — see the approval
            # endpoint for why.
            events.append(
                _event(
                    "approval_required",
                    order_id=data["order_id"],
                    audit_id=data.get("audit_id"),
                    total=data.get("total"),
                    product=data.get("product"),
                    reason=(data.get("guardrail") or {}).get("reason"),
                )
            )
        return events
    return []


async def run_turn(
    deps: AgentDeps,
    messages: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Run one chat turn, yielding events as the graph produces them."""
    _validate_tool_coverage()
    compiled = build_graph(deps)

    initial: AgentState = {
        "conversation_id": deps.conversation_id,
        "messages": messages,
        "pending_calls": [],
        "tool_results": [],
        "events": [],
        "iterations": 0,
    }

    seen = 0
    final_state: dict[str, Any] = {}

    # `values` mode emits the full state after each node, so events accumulated
    # by that node become available as soon as it finishes rather than at the end.
    async for state in compiled.astream(initial, stream_mode="values"):
        final_state = state
        events = state.get("events") or []
        for event in events[seen:]:
            yield event
        seen = len(events)

    yield _event(
        "state",
        messages=final_state.get("messages", messages),
        intent=final_state.get("intent"),
        error=final_state.get("error"),
    )
