"""Tool registry contract tests.

Synchronous by design — these assert on tool *declarations*, not behaviour.
"""

from __future__ import annotations

import pytest

from app.tools import ToolSpec, registry
from app.tools.base import ToolRegistry


def test_catalog_tools_are_registered() -> None:
    assert registry.names() == ["get_product", "search_catalog"]


def test_no_catalog_tool_claims_to_move_money() -> None:
    """Read-only tools must not be flagged for the guardrail path."""
    assert registry.money_tools() == []


def test_tool_definitions_render_for_the_messages_api() -> None:
    defs = {t["name"]: t for t in registry.to_anthropic()}
    assert set(defs) == {"get_product", "search_catalog"}

    for name, d in defs.items():
        assert d["description"].strip(), f"{name} has no description"
        assert d["input_schema"]["type"] == "object"
        # additionalProperties:false keeps the model from inventing parameters.
        assert d["input_schema"]["additionalProperties"] is False

    assert defs["get_product"]["input_schema"]["required"] == ["product_id"]


def test_tool_descriptions_state_the_money_unit() -> None:
    """A model that assumes rupees instead of paise would be off by 100x."""
    for d in registry.to_anthropic():
        assert "MINOR UNITS" in d["description"]


def test_registering_a_duplicate_name_is_rejected() -> None:
    """Two tools sharing a name would make dispatch ambiguous."""
    local = ToolRegistry()
    spec = ToolSpec(
        name="dupe",
        description="x",
        input_schema={"type": "object", "properties": {}},
        handler=lambda session, **kw: None,  # type: ignore[arg-type,return-value]
    )
    local.register(spec)

    with pytest.raises(ValueError, match="already registered"):
        local.register(spec)
