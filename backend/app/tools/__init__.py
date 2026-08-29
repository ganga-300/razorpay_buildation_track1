"""Agent-callable tools.

Importing this package registers every tool. Import it (rather than the
submodules) anywhere the full registry is needed, so the set of available tools
has exactly one definition point.
"""

from __future__ import annotations

from app.tools import catalog as _catalog  # noqa: F401  — import registers tools
from app.tools import orders as _orders  # noqa: F401  — import registers tools
from app.tools.base import (
    ToolError,
    ToolRegistry,
    ToolSpec,
    err,
    execute_tool,
    ok,
    registry,
)

__all__ = [
    "ToolError",
    "ToolRegistry",
    "ToolSpec",
    "err",
    "execute_tool",
    "ok",
    "registry",
]
