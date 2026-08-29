"""LLM access for the purchasing agent.

The agent talks to a narrow `LLMClient` protocol rather than to the Anthropic
SDK directly. That keeps the graph fully testable without credentials — the test
suite injects a scripted client and exercises every branch of the state machine,
including the money paths, with no network and no spend.

Model calls go through the official `anthropic` SDK. LangGraph owns the state
machine; it does not own the model call.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """One completed assistant turn."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    # Raw content blocks, JSON-serialisable, for replay on the next turn.
    content: list[dict[str, Any]] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMUnavailable(Exception):
    """Raised when the model cannot be reached or is not configured."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class LLMClient(Protocol):
    """What the agent needs from a language model."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> LLMResponse: ...

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield ('text', delta) events, then exactly one ('final', LLMResponse)."""
        ...


def serialise_blocks(content: Any) -> list[dict[str, Any]]:
    """Convert SDK content blocks to JSON for storage and replay.

    Thinking blocks are kept verbatim, signature included. Claude requires them
    echoed back unchanged when a conversation continues on the same model, and
    the transcript is persisted between HTTP requests, so they must survive the
    round trip through the database.
    """
    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict):
            blocks.append(block)
        else:
            blocks.append(block.model_dump(mode="json", exclude_none=True))
    return blocks


def extract_text(content: list[dict[str, Any]]) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def extract_tool_calls(content: list[dict[str, Any]]) -> list[ToolCall]:
    return [
        ToolCall(id=b["id"], name=b["name"], arguments=b.get("input") or {})
        for b in content
        if b.get("type") == "tool_use"
    ]


class AnthropicLLMClient:
    """`LLMClient` backed by the official Anthropic SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _require_client(self) -> Any:
        if not self.configured:
            raise LLMUnavailable(
                "ANTHROPIC_API_KEY is not set, so the purchasing agent cannot "
                "reason. Add it to the backend .env and restart."
            )
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    def _request_kwargs(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
        effort: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": system,
            "messages": messages,
            # Adaptive thinking: the model decides how much to reason per turn.
            # `budget_tokens` is rejected on this model generation.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort or settings.anthropic_effort},
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> LLMResponse:
        client = self._require_client()
        kwargs = self._request_kwargs(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
        )
        try:
            message = await client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error below
            raise _as_unavailable(exc) from exc

        content = serialise_blocks(message.content)
        return LLMResponse(
            text=extract_text(content),
            tool_calls=extract_tool_calls(content),
            stop_reason=message.stop_reason or "end_turn",
            content=content,
        )

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream text deltas, then the assembled final response."""
        client = self._require_client()
        kwargs = self._request_kwargs(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
        )
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield ("text", text)
                message = await stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error below
            raise _as_unavailable(exc) from exc

        content = serialise_blocks(message.content)
        yield (
            "final",
            LLMResponse(
                text=extract_text(content),
                tool_calls=extract_tool_calls(content),
                stop_reason=message.stop_reason or "end_turn",
                content=content,
            ),
        )


def _as_unavailable(exc: Exception) -> LLMUnavailable:
    """Classify SDK failures so the agent knows whether a retry could help."""
    if isinstance(exc, LLMUnavailable):
        return exc

    name = type(exc).__name__
    retryable = name in {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
    }
    logger.warning("LLM call failed (%s): %s", name, exc)
    return LLMUnavailable(f"Model request failed ({name}): {exc}", retryable=retryable)


_client: AnthropicLLMClient | None = None


def get_llm_client() -> AnthropicLLMClient:
    """Process-wide client; the SDK holds a connection pool."""
    global _client
    if _client is None:
        _client = AnthropicLLMClient()
    return _client
