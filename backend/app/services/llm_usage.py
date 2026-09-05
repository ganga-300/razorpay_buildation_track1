"""LLM token usage and cost accounting.

Every call the agent makes to Claude is recorded here — model, purpose, and the
four token counts Anthropic returns (`input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`). Nothing about this
was tracked before: the system had no way to say what a conversation actually
cost, which made "reduce spend" a matter of architectural argument rather than
measurement. This turns it into a number.

Pricing and the cache-write/cache-read multipliers below are the two structural
facts prompt caching's economics rest on. They are cited here as constants, not
scattered across call sites, so a price change is a one-line update.

    Model              Input $/MTok   Output $/MTok
    claude-opus-5      5.00           25.00
    claude-haiku-4-5    1.00           5.00

    Cache write (creating a new cache entry)   : 1.25x the input rate
    Cache read  (reusing an existing entry)    : 0.10x the input rate

This is an in-process counter — correct for the single-instance deployment this
project actually runs on, and reset on every restart. It is not a substitute for
Anthropic's own Usage & Cost Admin API for anything that needs to survive a
restart or span multiple instances; it exists to make the effect of the rules in
this file visible without leaving the codebase.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# $ per million tokens. Only the two models this project actually calls need an
# entry — anything else raises rather than silently costing $0 in the report.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def _price(model: str) -> dict[str, float]:
    try:
        return MODEL_PRICING[model]
    except KeyError:
        raise ValueError(
            f"No pricing entry for model {model!r}. Add one to MODEL_PRICING "
            "before this model can be billed for in the usage report — a "
            "silent $0 would make the numbers wrong, not just incomplete."
        ) from None


def _cost_minor_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
) -> float:
    """Dollar cost of one call, from its raw token counts."""
    price = _price(model)
    return (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + cache_creation_input_tokens * price["input"] * CACHE_WRITE_MULTIPLIER
        + cache_read_input_tokens * price["input"] * CACHE_READ_MULTIPLIER
    ) / 1_000_000


@dataclass
class _Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0

    def add(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int,
        cache_read_input_tokens: int,
        cost_usd: float,
        calls: int = 1,
    ) -> None:
        """Fold in one call's worth of usage.

        `calls` defaults to 1 for the common case of recording a single real
        API call. `snapshot()`'s grand-total merge is the one place that folds
        in an already-aggregated bucket rather than a single call, and it must
        pass that bucket's own `calls` count explicitly — otherwise merging N
        buckets counts as N calls total instead of the real, larger number.
        """
        self.calls += calls
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        self.cost_usd += cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class _ShortCircuitTotals:
    """Intent calls answered by the exact-match lookup — no API call at all."""

    count: int = 0
    # What those calls would have cost had they gone to the LLM, at the
    # intent-classification model's own price and the observed average call
    # shape. Populated lazily once at least one real intent call has run.
    would_have_cost_usd: float = 0.0


_lock = threading.Lock()
_totals: dict[tuple[str, str], _Totals] = {}
_short_circuited = _ShortCircuitTotals()


def record_llm_call(
    *,
    purpose: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Record one real API call and return its cost in USD."""
    cost = _cost_minor_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    with _lock:
        key = (purpose, model)
        bucket = _totals.setdefault(key, _Totals())
        bucket.add(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cost_usd=cost,
        )
    return cost


def record_short_circuited_intent(*, reference_model: str) -> None:
    """An intent call answered by exact-match lookup, at zero API cost.

    The counterfactual cost uses the average observed token shape for real
    intent calls on `reference_model` so far. Before any real intent call has
    run there is nothing to average, so the counterfactual stays at zero rather
    than guessing — a call this cheap and this rare is not worth a hardcoded
    token estimate.
    """
    with _lock:
        _short_circuited.count += 1
        bucket = _totals.get(("intent", reference_model))
        if bucket and bucket.calls:
            avg_input = bucket.input_tokens / bucket.calls
            avg_output = bucket.output_tokens / bucket.calls
            _short_circuited.would_have_cost_usd += _cost_minor_usd(
                reference_model,
                input_tokens=int(avg_input),
                output_tokens=int(avg_output),
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )


def snapshot() -> dict[str, Any]:
    """The full accounting: per-route totals, cache economics, and what the
    two cost-reduction rules (model tiering, short-circuiting) have saved."""
    with _lock:
        by_route = {
            f"{purpose}:{model}": bucket.as_dict()
            for (purpose, model), bucket in sorted(_totals.items())
        }
        grand = _Totals()
        for bucket in _totals.values():
            grand.add(
                input_tokens=bucket.input_tokens,
                output_tokens=bucket.output_tokens,
                cache_creation_input_tokens=bucket.cache_creation_input_tokens,
                cache_read_input_tokens=bucket.cache_read_input_tokens,
                cost_usd=bucket.cost_usd,
                calls=bucket.calls,
            )

        cacheable = (
            grand.input_tokens
            + grand.cache_creation_input_tokens
            + grand.cache_read_input_tokens
        )
        cache_hit_rate = (
            grand.cache_read_input_tokens / cacheable if cacheable else 0.0
        )

        # What the cache-read tokens would have cost at full input price, had
        # caching not been in play — computed per route so each side uses its
        # own model's price, then summed.
        saved_by_caching = 0.0
        for (purpose, model), bucket in _totals.items():
            if not bucket.cache_read_input_tokens:
                continue
            price = _price(model)["input"]
            full_price = bucket.cache_read_input_tokens * price / 1_000_000
            actual_price = (
                bucket.cache_read_input_tokens
                * price
                * CACHE_READ_MULTIPLIER
                / 1_000_000
            )
            saved_by_caching += full_price - actual_price

        # What intent calls actually spent on the cheap model, vs. what the
        # same token counts would have cost on Opus 5 — the model this project
        # used for every call before intent classification was moved off it.
        saved_by_model_tiering = 0.0
        for (purpose, model), bucket in _totals.items():
            if purpose != "intent" or model == "claude-opus-5" or not bucket.calls:
                continue
            counterfactual = _cost_minor_usd(
                "claude-opus-5",
                input_tokens=bucket.input_tokens,
                output_tokens=bucket.output_tokens,
                cache_creation_input_tokens=bucket.cache_creation_input_tokens,
                cache_read_input_tokens=bucket.cache_read_input_tokens,
            )
            saved_by_model_tiering += counterfactual - bucket.cost_usd

        return {
            "by_route": by_route,
            "totals": grand.as_dict(),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "savings": {
                "from_prompt_caching_usd": round(saved_by_caching, 6),
                "from_model_tiering_usd": round(saved_by_model_tiering, 6),
                "from_short_circuited_intents": {
                    "count": _short_circuited.count,
                    "would_have_cost_usd": round(
                        _short_circuited.would_have_cost_usd, 6
                    ),
                },
            },
            "pricing_reference": MODEL_PRICING,
        }


def reset() -> None:
    """Clear all counters. Used by tests; safe to call in production too."""
    with _lock:
        _totals.clear()
        _short_circuited.count = 0
        _short_circuited.would_have_cost_usd = 0.0
