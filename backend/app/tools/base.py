"""Agent tool registry.

A tool is a named, JSON-schema-described capability the purchasing agent may
invoke. Three properties matter for this project:

* **Uniform envelope.** Every tool returns ``{"ok": true, "data": ...}`` or
  ``{"ok": false, "error": {...}}``. A tool never raises into the agent loop, so
  a failure becomes something the model can read and explain to the buyer rather
  than a stack trace that kills the turn. This is the substrate for the
  gracefully-handled failure in Milestone 4.
* **Declared money-mutation.** ``mutates_money`` marks the tools that must pass
  through `services/guardrails.py` and be written to the audit trail. The agent
  executor enforces this from the flag, so a new money tool cannot be added and
  accidentally skip the gate.
* **One schema, two consumers.** ``to_anthropic()`` renders the same spec the
  API needs, so tool definitions never drift from their implementations.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A failure the agent is expected to handle and explain, not crash on."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            **({"details": self.details} if self.details else {}),
        }


class ToolHandler(Protocol):
    """Handlers receive a DB session plus the model-supplied arguments."""

    def __call__(self, session: AsyncSession, **kwargs: Any) -> Awaitable[dict[str, Any]]: ...


@dataclass(frozen=True)
class ToolSpec:
    """A single agent-callable capability."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    mutates_money: bool = False

    def to_anthropic(self) -> dict[str, Any]:
        """Render as an Anthropic Messages API tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolRegistry:
    """Ordered collection of tools exposed to the agent."""

    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"Tool {spec.name!r} is already registered")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(
                "unknown_tool",
                f"No tool named {name!r}. Available: {', '.join(sorted(self._tools))}",
            ) from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def to_anthropic(self) -> list[dict[str, Any]]:
        """The full tool list in Anthropic Messages API form."""
        return [t.to_anthropic() for t in self.all()]

    def money_tools(self) -> list[str]:
        return [t.name for t in self.all() if t.mutates_money]


registry = ToolRegistry()


def ok(data: Any) -> dict[str, Any]:
    """Success envelope."""
    return {"ok": True, "data": data}


def err(error: ToolError) -> dict[str, Any]:
    """Failure envelope."""
    return {"ok": False, "error": error.to_payload()}


async def execute_tool(
    name: str,
    session: AsyncSession,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke a registered tool, converting every failure into an envelope.

    Unknown argument names are dropped rather than raising, because models
    occasionally invent a plausible extra parameter and that should degrade to a
    slightly-wrong query, not a dead turn.
    """
    arguments = arguments or {}

    try:
        spec = registry.get(name)
    except ToolError as exc:
        return err(exc)

    accepted = _accepted_parameters(spec.handler)
    if accepted is not None:
        dropped = set(arguments) - accepted
        if dropped:
            logger.warning("Tool %s: dropping unexpected arguments %s", name, sorted(dropped))
            arguments = {k: v for k, v in arguments.items() if k in accepted}

    try:
        return ok(await spec.handler(session, **arguments))
    except ToolError as exc:
        logger.info("Tool %s returned a handled error: %s", name, exc.code)
        return err(exc)
    except TypeError as exc:
        return err(ToolError("invalid_arguments", f"Bad arguments for {name!r}: {exc}"))
    except Exception as exc:  # noqa: BLE001 — the agent loop must never die
        logger.exception("Tool %s raised an unexpected error", name)
        return err(
            ToolError(
                "internal_error",
                f"{name!r} failed unexpectedly: {exc}",
                retryable=True,
            )
        )


def _accepted_parameters(handler: ToolHandler) -> set[str] | None:
    """Parameter names a handler accepts, or None if it takes **kwargs."""
    sig = inspect.signature(handler)
    names: set[str] = set()
    for pname, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return None
        if pname != "session":
            names.add(pname)
    return names
