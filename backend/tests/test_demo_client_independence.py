"""The demo MCP client must stay independent of the merchant.

The interoperability claim rests on one fact: `demo/mcp_buyer.py` is a buyer
that shares no code with AutoBuy. That is easy to say and easy to break — one
convenience import of a shared constant and the demo quietly stops proving
anything.

This parses the file and fails if it ever imports application code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DEMO_CLIENT = Path(__file__).resolve().parents[2] / "demo" / "mcp_buyer.py"

# The buyer side may know the protocol and the standard library. Nothing else.
ALLOWED_ROOTS = {"mcp", "asyncio", "argparse", "sys", "os", "json", "time", "__future__"}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_demo_client_exists() -> None:
    assert DEMO_CLIENT.exists(), f"missing: {DEMO_CLIENT}"


def test_the_demo_client_imports_no_application_code() -> None:
    """One shared import and the demo stops proving interoperability."""
    roots = imported_roots(DEMO_CLIENT)
    forbidden = roots - ALLOWED_ROOTS
    assert not forbidden, (
        f"demo/mcp_buyer.py imports {sorted(forbidden)}. It must depend only on "
        "the MCP SDK and the standard library, or it no longer demonstrates that "
        "an independent agent can transact with this merchant."
    )


def test_the_demo_client_speaks_mcp() -> None:
    """Guard against the file being gutted into something that proves nothing."""
    assert "mcp" in imported_roots(DEMO_CLIENT)


@pytest.mark.parametrize("forbidden", ["app.services", "app.tools", "from app import"])
def test_no_application_imports_appear_even_in_text(forbidden: str) -> None:
    """Belt and braces: catches a lazy import inside a function body too."""
    assert forbidden not in DEMO_CLIENT.read_text()
