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
    # input_tokens / output_tokens / cache_creation_input_tokens /
    # cache_read_input_tokens, straight from `message.usage`. Empty for a
    # client that never talked to a real API (the scripted planner, test
    # fakes) — there is nothing to have spent.
    usage: dict[str, int] = field(default_factory=dict)

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
        model: str | None = None,
        purpose: str = "agent",
    ) -> LLMResponse: ...

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
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



# Models known to run WITHOUT adaptive thinking / the `effort` parameter.
# Haiku 4.5 takes neither: sending `output_config.effort` to it is a 400
# ("errors on ... Haiku 4.5" per the model family's documented behaviour), and
# omitting `thinking` entirely is what makes it run with no extended-thinking
# overhead at all — exactly what a 5-way classification call should cost.
# Every other model this project uses (the Opus tier) supports both and is
# reasoned about elsewhere in this file as "the default"; this set exists so a
# genuinely different model doesn't silently inherit Opus-shaped request
# fields it cannot accept.
_NO_THINKING_NO_EFFORT_MODELS = frozenset({"claude-haiku-4-5"})


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
        model: str | None,
    ) -> tuple[dict[str, Any], str]:
        resolved_model = model or self.model

        # Prompt caching: the system prompt plus the tool schemas are ~1.6K
        # static tokens resent on every iteration of every tool-calling round,
        # for every turn, for every buyer — currently at full price with zero
        # reuse. Anthropic renders `tools` before `system`, so a single
        # breakpoint on the (last block of the) system prompt caches both
        # together. Only worth doing when `tools` is present: that is the one
        # call shape big enough to clear even Claude Opus 5's lowest-in-class
        # 512-token minimum (the plain intent-classification prompt is ~110
        # tokens and would never cross it — a marker there would only pay the
        # write premium for zero reads, ever).
        if tools:
            system_field: str | list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_field = system

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": system_field,
            "messages": messages,
        }

        if resolved_model not in _NO_THINKING_NO_EFFORT_MODELS:
            # Adaptive thinking: the model decides how much to reason per turn.
            # `budget_tokens` is rejected on this model generation.
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": effort or settings.anthropic_effort}

        if tools:
            kwargs["tools"] = tools
        return kwargs, resolved_model

    @staticmethod
    def _usage_dict(message: Any) -> dict[str, int]:
        usage = getattr(message, "usage", None)
        if usage is None:
            return {}
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
        }

    def _record(self, *, purpose: str, model: str, usage: dict[str, int]) -> None:
        if not usage:
            return
        from app.services.llm_usage import record_llm_call

        record_llm_call(purpose=purpose, model=model, **usage)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> LLMResponse:
        client = self._require_client()
        kwargs, resolved_model = self._request_kwargs(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
            model=model,
        )
        try:
            message = await client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error below
            raise _as_unavailable(exc) from exc

        usage = self._usage_dict(message)
        self._record(purpose=purpose, model=resolved_model, usage=usage)

        content = serialise_blocks(message.content)
        return LLMResponse(
            text=extract_text(content),
            tool_calls=extract_tool_calls(content),
            stop_reason=message.stop_reason or "end_turn",
            content=content,
            usage=usage,
        )

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream text deltas, then the assembled final response."""
        client = self._require_client()
        kwargs, resolved_model = self._request_kwargs(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
            model=model,
        )
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield ("text", text)
                message = await stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error below
            raise _as_unavailable(exc) from exc

        usage = self._usage_dict(message)
        self._record(purpose=purpose, model=resolved_model, usage=usage)

        content = serialise_blocks(message.content)
        yield (
            "final",
            LLMResponse(
                text=extract_text(content),
                tool_calls=extract_tool_calls(content),
                stop_reason=message.stop_reason or "end_turn",
                content=content,
                usage=usage,
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


def get_agent_client() -> LLMClient:
    """The brain for a chat turn: Claude, or the deterministic planner.

    Scripted mode is selected explicitly by `AGENT_MODE=scripted`. It is never a
    silent fallback — an unset or unfunded key in `model` mode produces a clear
    error rather than quietly degrading to keyword matching, because a buyer has
    a right to know whether a model or a rule table is spending their money.
    """
    if settings.agent_mode == "scripted":
        from app.agents.scripted_planner import ScriptedPlanner

        return ScriptedPlanner()
    return get_llm_client()


def agent_mode_label() -> str:
    return "scripted" if settings.agent_mode == "scripted" else settings.anthropic_model
