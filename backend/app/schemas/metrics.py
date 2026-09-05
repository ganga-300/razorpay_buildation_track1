"""Response schema for the LLM cost/usage report."""

from __future__ import annotations

from pydantic import BaseModel


class RouteTotals(BaseModel):
    """Accumulated usage for one (purpose, model) pair since the process started."""

    calls: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float


class ShortCircuitedIntents(BaseModel):
    """Intent calls answered by exact-match lookup — no API call at all."""

    count: int
    would_have_cost_usd: float


class Savings(BaseModel):
    """What each cost-reduction rule has measurably saved, in dollars."""

    from_prompt_caching_usd: float
    from_model_tiering_usd: float
    from_short_circuited_intents: ShortCircuitedIntents


class ModelPrice(BaseModel):
    input: float
    output: float


class LLMMetricsResponse(BaseModel):
    """Everything the agent has spent on Claude since the process started.

    In-process counters, reset on restart — see `app/services/llm_usage.py`
    for what this can and cannot stand in for.
    """

    by_route: dict[str, RouteTotals]
    totals: RouteTotals
    cache_hit_rate: float
    savings: Savings
    pricing_reference: dict[str, ModelPrice]
