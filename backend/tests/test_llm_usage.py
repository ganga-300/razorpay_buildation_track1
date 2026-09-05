"""Tests for `app/services/llm_usage.py` — the cost/usage accounting itself.

These are pure-math tests: no model, no network, no graph. They exist because
the accounting is what every cost claim in this project is measured against —
a bug here makes every number downstream wrong, not just this module.
"""

from __future__ import annotations

from app.services import llm_usage


def test_recording_a_call_returns_and_accumulates_its_cost() -> None:
    cost = llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # 1M input tokens @ $5/MTok + 1M output tokens @ $25/MTok.
    assert cost == 30.0

    snap = llm_usage.snapshot()
    assert snap["totals"]["cost_usd"] == 30.0
    assert snap["totals"]["calls"] == 1


def test_cache_write_costs_more_than_a_plain_input_token() -> None:
    """1.25x the input rate — writing a cache entry is not free."""
    cost = llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
    )
    assert cost == 5.0 * 1.25


def test_cache_read_costs_a_tenth_of_a_plain_input_token() -> None:
    cost = llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
    )
    assert cost == 5.0 * 0.10


def test_an_unpriced_model_raises_rather_than_costing_zero_silently() -> None:
    """A silent $0 would make the report wrong, not just incomplete."""
    import pytest

    with pytest.raises(ValueError, match="No pricing entry"):
        llm_usage.record_llm_call(
            purpose="agent", model="claude-sonnet-5", input_tokens=10, output_tokens=10
        )


def test_grand_totals_count_every_call_not_every_route() -> None:
    """Regression: merging per-route buckets into a grand total once counted
    ROUTES, not CALLS — three calls across two routes reported as 2, not 3."""
    llm_usage.record_llm_call(purpose="agent", model="claude-opus-5", input_tokens=1, output_tokens=1)
    llm_usage.record_llm_call(purpose="agent", model="claude-opus-5", input_tokens=1, output_tokens=1)
    llm_usage.record_llm_call(purpose="intent", model="claude-haiku-4-5", input_tokens=1, output_tokens=1)

    snap = llm_usage.snapshot()
    assert snap["totals"]["calls"] == 3
    assert snap["by_route"]["agent:claude-opus-5"]["calls"] == 2
    assert snap["by_route"]["intent:claude-haiku-4-5"]["calls"] == 1


def test_cache_hit_rate_is_read_tokens_over_all_cacheable_tokens() -> None:
    llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=100,
        output_tokens=1,
        cache_read_input_tokens=900,
    )
    snap = llm_usage.snapshot()
    assert snap["cache_hit_rate"] == 0.9


def test_savings_from_caching_is_the_gap_between_read_price_and_full_price() -> None:
    llm_usage.record_llm_call(
        purpose="agent",
        model="claude-opus-5",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
    )
    snap = llm_usage.snapshot()
    # Would have cost $5.00 at full price; actually cost $0.50 (0.1x) — $4.50 saved.
    assert snap["savings"]["from_prompt_caching_usd"] == 5.0 - 0.5


def test_savings_from_model_tiering_is_the_opus_counterfactual() -> None:
    """What the SAME token counts would have cost on the model this project
    used for every call before intent classification moved off Opus 5."""
    llm_usage.record_llm_call(
        purpose="intent",
        model="claude-haiku-4-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    snap = llm_usage.snapshot()
    actual = 1.0 + 5.0  # Haiku: $1/$25 per MTok inputs/outputs at 1M each -> $1 + $5
    counterfactual = 5.0 + 25.0  # same token counts at Opus 5 pricing
    assert snap["savings"]["from_model_tiering_usd"] == counterfactual - actual


def test_model_tiering_savings_ignore_calls_already_on_opus() -> None:
    """A route that already runs on Opus 5 has no counterfactual to speak of."""
    llm_usage.record_llm_call(
        purpose="agent", model="claude-opus-5", input_tokens=100, output_tokens=100
    )
    snap = llm_usage.snapshot()
    assert snap["savings"]["from_model_tiering_usd"] == 0.0


def test_short_circuited_intents_have_no_counterfactual_before_any_real_call() -> None:
    """Nothing to average yet — the counterfactual must not guess a number."""
    llm_usage.record_short_circuited_intent(reference_model="claude-haiku-4-5")
    snap = llm_usage.snapshot()
    assert snap["savings"]["from_short_circuited_intents"] == {
        "count": 1,
        "would_have_cost_usd": 0.0,
    }


def test_short_circuited_intents_use_the_observed_average_once_available() -> None:
    llm_usage.record_llm_call(
        purpose="intent", model="claude-haiku-4-5", input_tokens=100, output_tokens=10
    )
    llm_usage.record_short_circuited_intent(reference_model="claude-haiku-4-5")

    snap = llm_usage.snapshot()
    expected = (100 * 1.0 + 10 * 5.0) / 1_000_000
    assert snap["savings"]["from_short_circuited_intents"]["count"] == 1
    assert snap["savings"]["from_short_circuited_intents"]["would_have_cost_usd"] == expected


def test_reset_clears_everything() -> None:
    llm_usage.record_llm_call(purpose="agent", model="claude-opus-5", input_tokens=1, output_tokens=1)
    llm_usage.record_short_circuited_intent(reference_model="claude-haiku-4-5")
    llm_usage.reset()

    snap = llm_usage.snapshot()
    assert snap["totals"]["calls"] == 0
    assert snap["by_route"] == {}
    assert snap["savings"]["from_short_circuited_intents"]["count"] == 0
