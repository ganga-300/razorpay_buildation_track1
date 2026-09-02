"""Tool registry contract tests.

Synchronous by design — these assert on tool *declarations*, not behaviour.
The invariants are written to stay true as tools are added.
"""

from __future__ import annotations

import pytest

from app.agents.purchasing_agent import TOOL_PHASES, _validate_tool_coverage
from app.tools import ToolSpec, registry
from app.tools.base import ToolRegistry

GATED_NODES = {"create_order", "verify_payment"}


def test_every_expected_tool_is_registered() -> None:
    assert registry.names() == [
        "create_order",
        "get_order_status",
        "get_product",
        "search_catalog",
        "verify_payment",
    ]


def test_money_tools_are_exactly_the_ones_that_move_money() -> None:
    """Mislabelling here would route a charge around the Milestone 4 gate."""
    assert registry.money_tools() == ["create_order", "verify_payment"]


def test_read_only_tools_are_not_flagged_as_money_tools() -> None:
    money = set(registry.money_tools())
    assert "search_catalog" not in money
    assert "get_product" not in money
    # Polling an order's status is a read; it must never be gated as spend.
    assert "get_order_status" not in money


def test_tool_definitions_render_for_the_messages_api() -> None:
    defs = {t["name"]: t for t in registry.to_anthropic()}
    assert set(defs) == set(registry.names())

    for name, d in defs.items():
        assert d["description"].strip(), f"{name} has no description"
        assert d["input_schema"]["type"] == "object"
        # additionalProperties:false keeps the model from inventing parameters.
        assert d["input_schema"]["additionalProperties"] is False

    assert defs["get_product"]["input_schema"]["required"] == ["product_id"]
    assert defs["create_order"]["input_schema"]["required"] == ["product_id"]


def test_tools_taking_money_amounts_state_the_unit() -> None:
    """A model that assumes rupees instead of paise would be off by 100x.

    Scoped to tools that actually accept a money amount — `create_order` takes
    no amount at all (the total is computed server-side from the catalog), so
    requiring the phrase everywhere would be noise.
    """
    for spec in registry.all():
        takes_amount = any(
            prop.endswith("_minor") for prop in spec.input_schema["properties"]
        )
        if takes_amount:
            assert "MINOR UNITS" in spec.description, (
                f"{spec.name} accepts a minor-unit amount but never says so"
            )


def test_create_order_does_not_let_the_model_choose_the_price() -> None:
    """The amount charged must come from the catalog, never from the model."""
    schema = registry.get("create_order").input_schema
    assert set(schema["properties"]) == {"product_id", "quantity"}


def test_every_money_tool_is_routed_to_a_gated_node() -> None:
    """Structural guarantee that money cannot flow through the catalog path."""
    for name in registry.money_tools():
        assert TOOL_PHASES[name] in GATED_NODES


def test_tool_coverage_validation_passes() -> None:
    """Raises if any registered tool has no node, or a money tool is misrouted."""
    _validate_tool_coverage()


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
