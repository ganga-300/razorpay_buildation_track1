"""Agent/SSE event-registry contract.

Synchronous by design — these assert on declarations, not behaviour.
"""

from __future__ import annotations


def test_every_emitted_event_is_registered() -> None:
    """Catch an event the agent emits but the SSE layer would silently drop.

    `guardrail` and `approval_required` were added to the agent and dropped by a
    hand-maintained forward list; the approval gate rendered as a bare status
    badge with no Approve button and nothing errored. This scans the agent
    source for every `_event("...")` literal and asserts it is registered.
    """
    import re
    from pathlib import Path

    from app.agents import purchasing_agent
    from app.agents.purchasing_agent import AGENT_EVENT_TYPES

    source = Path(purchasing_agent.__file__).read_text()
    emitted = set(re.findall(r'_event\(\s*"([a-z_]+)"', source))

    assert emitted, "no _event() calls found — did the helper get renamed?"
    unregistered = emitted - AGENT_EVENT_TYPES
    assert not unregistered, (
        f"emitted but not in AGENT_EVENT_TYPES: {sorted(unregistered)}"
    )


def test_client_events_forward_everything_except_internal() -> None:
    from app.agents.purchasing_agent import AGENT_EVENT_TYPES, INTERNAL_EVENT_TYPES
    from app.api.chat import CLIENT_EVENTS

    assert CLIENT_EVENTS == AGENT_EVENT_TYPES - INTERNAL_EVENT_TYPES
    assert "state" not in CLIENT_EVENTS
    assert {"guardrail", "approval_required"} <= CLIENT_EVENTS
