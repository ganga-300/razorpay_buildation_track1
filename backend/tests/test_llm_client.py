"""Tests for `AnthropicLLMClient`'s request shape: the actual cost-reduction
mechanics — prompt caching, per-call model override, and usage recording.

No network: `_client` is replaced with a fake that records exactly the kwargs
`messages.create()` / `messages.stream()` would have received, so these assert
on the real request Anthropic would see rather than on this project's own
description of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.llm import AnthropicLLMClient
from app.services import llm_usage

pytestmark = pytest.mark.asyncio

TOOLS = [
    {
        "name": "search_catalog",
        "description": "d",
        "input_schema": {"type": "object", "properties": {}},
    }
]


class _Usage:
    def __init__(self, i: int, o: int, cw: int = 0, cr: int = 0) -> None:
        self.input_tokens = i
        self.output_tokens = o
        self.cache_creation_input_tokens = cw
        self.cache_read_input_tokens = cr


class _Message:
    def __init__(self, usage: _Usage) -> None:
        self.content: list[Any] = []
        self.stop_reason = "end_turn"
        self.usage = usage


class _FakeMessages:
    """Stands in for `client.messages`. Records the kwargs it was called with."""

    def __init__(self, usage: _Usage) -> None:
        self._usage = usage
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _Message:
        self.last_kwargs = kwargs
        return _Message(self._usage)


def client_with_fake(model: str, usage: _Usage) -> tuple[AnthropicLLMClient, _FakeMessages]:
    c = AnthropicLLMClient(api_key="sk-test", model=model)
    fake = _FakeMessages(usage)
    c._client = type("FakeSDK", (), {"messages": fake})()
    return c, fake


# --------------------------------------------------------------------------
# Prompt caching: only worth it where the prefix is big enough to matter
# --------------------------------------------------------------------------


async def test_a_tool_bearing_call_caches_the_system_prompt() -> None:
    """This is the call shape resent on every tool-loop iteration — the single
    biggest static, repeated, currently-uncached cost in the system."""
    client, fake = client_with_fake("claude-opus-5", _Usage(1000, 100))
    await client.complete(system="SYSTEM", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)

    system = fake.last_kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == "SYSTEM"


async def test_a_tool_free_call_does_not_attempt_to_cache() -> None:
    """The intent-classification prompt is ~110 tokens — Claude Opus 5's own
    512-token minimum would never let it cache. A marker there would only pay
    the cache-write premium for zero reads, ever."""
    client, fake = client_with_fake("claude-opus-5", _Usage(100, 5))
    await client.complete(system="Classify...", messages=[{"role": "user", "content": "hi"}])

    assert fake.last_kwargs["system"] == "Classify..."


# --------------------------------------------------------------------------
# Per-call model override: how intent classification gets off Opus 5
# --------------------------------------------------------------------------


async def test_a_model_override_is_sent_instead_of_the_clients_default() -> None:
    client, fake = client_with_fake("claude-opus-5", _Usage(1, 1))
    await client.complete(
        system="s", messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5"
    )
    assert fake.last_kwargs["model"] == "claude-haiku-4-5"


async def test_without_an_override_the_clients_own_model_is_used() -> None:
    client, fake = client_with_fake("claude-opus-5", _Usage(1, 1))
    await client.complete(system="s", messages=[{"role": "user", "content": "hi"}])
    assert fake.last_kwargs["model"] == "claude-opus-5"


@pytest.mark.parametrize("field", ["thinking", "output_config"])
async def test_haiku_gets_neither_thinking_nor_effort(field: str) -> None:
    """Haiku 4.5 takes `budget_tokens` (or no thinking) and errors on `effort`.
    Sending it Opus-shaped fields would be a 400 on a real account, and this is
    exactly the model the intent classifier is routed to — so this is the one
    request shape that must never regress silently."""
    client, fake = client_with_fake("claude-opus-5", _Usage(1, 1))
    await client.complete(
        system="s", messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5"
    )
    assert field not in fake.last_kwargs


async def test_opus_still_gets_adaptive_thinking_and_effort() -> None:
    """The model the buyer actually talks to keeps its full request shape —
    the cost rules must not spill over onto the call that carries UX quality."""
    client, fake = client_with_fake("claude-opus-5", _Usage(1, 1))
    await client.complete(system="s", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
    assert fake.last_kwargs["thinking"] == {"type": "adaptive"}
    assert "output_config" in fake.last_kwargs


# --------------------------------------------------------------------------
# Usage is recorded against the model that actually ran, not the client default
# --------------------------------------------------------------------------


async def test_usage_is_recorded_under_the_resolved_model_and_purpose() -> None:
    client, _ = client_with_fake("claude-opus-5", _Usage(200, 20, cw=0, cr=150))
    resp = await client.complete(
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5",
        purpose="intent",
    )

    assert resp.usage == {
        "input_tokens": 200,
        "output_tokens": 20,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 150,
    }

    snap = llm_usage.snapshot()
    assert "intent:claude-haiku-4-5" in snap["by_route"]
    assert "intent:claude-opus-5" not in snap["by_route"]


async def test_stream_records_usage_the_same_way_as_complete() -> None:
    client = AnthropicLLMClient(api_key="sk-test", model="claude-opus-5")

    class _FakeStreamCtx:
        def __init__(self, message: _Message) -> None:
            self._message = message

        async def __aenter__(self) -> "_FakeStreamCtx":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        @property
        async def text_stream(self):
            if False:
                yield ""  # pragma: no cover — empty async generator

        async def get_final_message(self) -> _Message:
            return self._message

    message = _Message(_Usage(50, 5))

    class _FakeMessagesStream:
        def stream(self, **kwargs: Any) -> _FakeStreamCtx:
            self.last_kwargs = kwargs
            return _FakeStreamCtx(message)

    fake = _FakeMessagesStream()
    client._client = type("FakeSDK", (), {"messages": fake})()

    events = [e async for e in client.stream(system="s", messages=[{"role": "user", "content": "hi"}])]
    final = next(payload for kind, payload in events if kind == "final")

    assert final.usage == {
        "input_tokens": 50,
        "output_tokens": 5,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    snap = llm_usage.snapshot()
    assert snap["by_route"]["agent:claude-opus-5"]["calls"] == 1
