"""Scripted planner unit tests.

Synchronous by design — pure functions, no graph, no database.
"""

from __future__ import annotations

import pytest

from app.agents.llm import get_agent_client
from app.agents.scripted_planner import ScriptedPlanner, _price_ceiling, _query_from
from app.config import settings


# --------------------------------------------------------------------------
# Mode selection
# --------------------------------------------------------------------------


def test_scripted_mode_is_not_the_default() -> None:
    """A missing key must never silently degrade into keyword matching.

    Asserts the *declared* default on the model, not the loaded singleton — the
    latter reflects whatever is in the local .env and would pass or fail based
    on the developer's machine.
    """
    from app.config import Settings

    assert Settings.model_fields["agent_mode"].default == "model"


def test_the_mode_switch_selects_the_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "agent_mode", "scripted")
    assert isinstance(get_agent_client(), ScriptedPlanner)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Regression: substring matching classified this as a CANCEL, because
        # "cancelling" contains "cancel" — the agent answered a request to see
        # headphones with "I won't order anything."
        ("show me noise cancelling headphones", "browse"),
        ("buy the cancelling headphones", "purchase"),
        ("stopwatch for running", "browse"),   # "stop" is not a cancellation
        ("cancel that", "cancel"),
        ("never mind", "cancel"),
        ("i have paid", "verify"),
        ("i need a mouse", "browse"),
        ("order it", "purchase"),
    ],
)
def test_intent_words_match_on_word_boundaries(text: str, expected: str) -> None:
    assert ScriptedPlanner()._classify(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("under 2000", 200_000),
        ("below Rs 1,299", 129_900),
        ("less than ₹500", 50_000),
        ("upto 750", 75_000),
        ("a 2 metre cable", None),   # a bare number is not a budget
        ("no limit", None),
    ],
)
def test_price_ceiling_parsing(text: str, expected: int | None) -> None:
    assert _price_ceiling(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("show me a usb-c cable", "cable usb"),      # the stray "c" is dropped
        ("I need a wireless mouse", "wireless mouse"),
        ("show me a bluetooth speaker", "bluetooth speaker"),
    ],
)
def test_query_construction_stays_tight(text: str, expected: str) -> None:
    """Catalog search is AND across tokens, so a loose query matches nothing."""
    assert _query_from(text) == expected
