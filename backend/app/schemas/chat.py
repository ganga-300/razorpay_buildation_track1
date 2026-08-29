"""Chat request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A buyer's message."""

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        description="Omit to start a new conversation; the id is returned in the first event.",
    )


class ConversationSummary(BaseModel):
    """Lightweight conversation record."""

    id: str
    turns: int
    last_intent: str | None
