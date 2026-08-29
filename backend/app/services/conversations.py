"""Conversation persistence.

Transcripts are stored so a chat turn can span HTTP requests. That matters more
than it looks: Milestone 4's approval gate depends on the agent remembering the
order it proposed, so that a later "yes, go ahead" can be tied to a specific
proposed amount rather than re-derived from scratch.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation

# Keep the replayed transcript bounded so a long thread cannot grow the request
# without limit. Trimming is turn-aware: see `_trim`.
MAX_STORED_MESSAGES = 60


def new_conversation_id() -> str:
    return f"conv-{uuid.uuid4().hex[:12]}"


def _trim(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the oldest turns, without orphaning a tool_result.

    A `tool_result` block is only valid if the `tool_use` it answers is still in
    the transcript. Cutting blindly at an index can leave a dangling result and
    the API rejects the whole request, so the cut point is advanced to the next
    plain user turn.
    """
    if len(messages) <= MAX_STORED_MESSAGES:
        return messages

    cut = len(messages) - MAX_STORED_MESSAGES
    while cut < len(messages):
        message = messages[cut]
        content = message.get("content")
        is_tool_result = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        if message.get("role") == "user" and not is_tool_result:
            break
        cut += 1

    return messages[cut:] if cut < len(messages) else messages[-2:]


async def get_or_create(
    session: AsyncSession, conversation_id: str | None
) -> Conversation:
    """Load a conversation, or start one."""
    if conversation_id:
        existing = await session.get(Conversation, conversation_id)
        if existing is not None:
            return existing

    conversation = Conversation(
        id=conversation_id or new_conversation_id(), messages=[]
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def save_messages(
    session: AsyncSession,
    conversation: Conversation,
    messages: list[dict[str, Any]],
    *,
    intent: str | None = None,
) -> None:
    """Persist the transcript after a turn."""
    conversation.messages = _trim(messages)
    if intent:
        conversation.last_intent = intent
    await session.commit()
