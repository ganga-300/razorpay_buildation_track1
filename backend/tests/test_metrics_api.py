"""`GET /metrics/llm` — the cost/usage report as the outside world sees it."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import llm_usage

pytestmark = pytest.mark.asyncio


async def test_empty_report_before_any_call(client: AsyncClient) -> None:
    body = (await client.get("/metrics/llm")).json()
    assert body["totals"]["calls"] == 0
    assert body["by_route"] == {}
    assert body["savings"]["from_prompt_caching_usd"] == 0.0
    assert "claude-opus-5" in body["pricing_reference"]
    assert "claude-haiku-4-5" in body["pricing_reference"]


async def test_report_reflects_recorded_calls(client: AsyncClient) -> None:
    llm_usage.record_llm_call(
        purpose="intent",
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=5,
    )
    llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=1500,
    )

    body = (await client.get("/metrics/llm")).json()
    assert body["totals"]["calls"] == 2
    assert set(body["by_route"]) == {"intent:claude-haiku-4-5", "agent:claude-opus-5"}
    assert body["by_route"]["agent:claude-opus-5"]["cache_read_input_tokens"] == 1500
    assert body["cache_hit_rate"] > 0
    assert body["savings"]["from_prompt_caching_usd"] > 0
