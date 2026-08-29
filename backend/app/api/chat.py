"""Conversational checkout endpoint.

`POST /chat` runs one agent turn and streams what happens as Server-Sent Events.
The buyer sees the agent think, search, and order in real time rather than
waiting for a single blocking response.

Two implementation notes that are easy to get wrong:

* **The stream owns its own database session.** A session injected by
  `Depends(get_session)` is closed when the endpoint function returns, which for
  a streaming response is *before* the generator has produced anything. Opening
  a session inside the generator keeps it alive for the whole stream.
* **Errors are streamed, not raised.** Once the response has begun there is no
  status code left to change, so a failure mid-turn is delivered as an `error`
  event the UI can render.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.agents.llm import get_llm_client
from app.agents.purchasing_agent import (
    AGENT_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    AgentDeps,
    run_turn,
)
from app.config import settings
from app.db.session import SessionLocal
from app.schemas.chat import ChatRequest
from app.services import conversations as conversation_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# What reaches the browser: everything the agent emits, minus the internal
# events. Derived rather than duplicated — a hand-maintained copy of this list
# silently dropped `guardrail` and `approval_required` once already.
CLIENT_EVENTS = AGENT_EVENT_TYPES - INTERNAL_EVENT_TYPES


def _sse(event: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False, default=str)}


async def _turn_stream(request: ChatRequest) -> AsyncIterator[dict[str, str]]:
    """Run one turn and yield SSE frames."""
    async with SessionLocal() as session:
        try:
            conversation = await conversation_service.get_or_create(
                session, request.conversation_id
            )
            conversation_id = conversation.id
            yield _sse("conversation", {"conversation_id": conversation_id})

            if not settings.anthropic_configured:
                yield _sse(
                    "error",
                    {
                        "code": "llm_not_configured",
                        "message": (
                            "ANTHROPIC_API_KEY is not set, so the purchasing agent "
                            "cannot reason. Add it to backend/.env and restart."
                        ),
                        "retryable": False,
                    },
                )
                return

            messages: list[dict[str, Any]] = [
                *(conversation.messages or []),
                {"role": "user", "content": request.message},
            ]

            deps = AgentDeps(
                session=session,
                llm=get_llm_client(),
                conversation_id=conversation_id,
            )

            final_messages = messages
            intent: str | None = None

            async for event in run_turn(deps, messages):
                kind = event.get("type", "")

                if kind == "state":
                    final_messages = event.get("messages", messages)
                    intent = event.get("intent")
                    if event.get("error"):
                        yield _sse("error", event["error"])
                    continue

                if kind in CLIENT_EVENTS:
                    yield _sse(kind, {k: v for k, v in event.items() if k != "type"})

            await conversation_service.save_messages(
                session, conversation, final_messages, intent=intent
            )
            yield _sse("end", {"conversation_id": conversation_id})

        except Exception as exc:  # noqa: BLE001 — the stream must close cleanly
            logger.exception("Chat turn failed")
            yield _sse(
                "error",
                {
                    "code": "internal_error",
                    "message": f"The turn failed: {exc}",
                    "retryable": True,
                },
            )


@router.post(
    "/chat",
    summary="Conversational checkout (Server-Sent Events)",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": (
                "An SSE stream. Event types: `conversation`, `intent`, `message`, "
                "`tool_call`, `tool_result`, `products`, `order`, `done`, `error`, `end`."
            ),
            "content": {"text/event-stream": {}},
        }
    },
)
async def chat(request: ChatRequest) -> EventSourceResponse:
    """Send a message to the purchasing agent and stream the response."""
    return EventSourceResponse(_turn_stream(request))
