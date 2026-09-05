"""Test doubles.

The scripted LLM client lets the whole graph — including both money paths — be
exercised with no API key, no network, and no spend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.agents.llm import LLMResponse, LLMUnavailable, extract_text, extract_tool_calls


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def tool_use_block(tool_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}


def response(*blocks: dict[str, Any], stop_reason: str | None = None) -> LLMResponse:
    """Build an LLMResponse from raw content blocks."""
    content = list(blocks)
    calls = extract_tool_calls(content)
    return LLMResponse(
        text=extract_text(content),
        tool_calls=calls,
        stop_reason=stop_reason or ("tool_use" if calls else "end_turn"),
        content=content,
    )


class ScriptedLLM:
    """Returns queued responses in order; records every request it received."""

    def __init__(
        self,
        turns: list[LLMResponse] | None = None,
        *,
        intents: list[str] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self._turns = list(turns or [])
        self._intents = list(intents or [])
        self._fail_with = fail_with
        self.calls: list[dict[str, Any]] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def turns_remaining(self) -> int:
        return len(self._turns)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "tools": [t["name"] for t in (tools or [])],
                "max_tokens": max_tokens,
                "effort": effort,
                "model": model,
                "purpose": purpose,
            }
        )

        # No tools bound => this is the intent-classification call.
        if not tools:
            if self._intents:
                return response(text_block(self._intents.pop(0)))
            return response(text_block("browse"))

        if self._fail_with is not None:
            raise self._fail_with

        if not self._turns:
            return response(text_block("(scripted client exhausted)"))
        return self._turns.pop(0)

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> AsyncIterator[tuple[str, Any]]:
        result = await self.complete(
            system=system,
            messages=messages,
            tools=tools,
            model=model,
            purpose=purpose,
            max_tokens=max_tokens,
            effort=effort,
        )
        if result.text:
            yield ("text", result.text)
        yield ("final", result)


class FakeRazorpay:
    """Stands in for the Razorpay SDK wrapper.

    Records every call so tests can assert on the exact amount sent to the
    provider, and can be told to fail so the failure path is exercised.
    """

    def __init__(
        self,
        *,
        fail_create: Exception | None = None,
        fail_verify: Exception | None = None,
        order_id: str = "order_TESTFAKE0001",
    ) -> None:
        self.fail_create = fail_create
        self.fail_verify = fail_verify
        self.order_id = order_id
        self.created: list[dict[str, Any]] = []
        self.verified: list[dict[str, Any]] = []
        self.issued_ids: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.created.append(
            {
                "amount_minor": amount_minor,
                "currency": currency,
                "receipt": receipt,
                "notes": notes or {},
            }
        )
        if self.fail_create is not None:
            raise self.fail_create

        # Razorpay issues a distinct id per order, and `orders.razorpay_order_id`
        # is UNIQUE. A fake that returns one id forever makes a second order
        # blow up on the constraint — a defect in the double, not the code.
        # The first id is `order_id` verbatim so tests can assert against it.
        issued = self.order_id if not self.issued_ids else f"{self.order_id}-{len(self.issued_ids)}"
        self.issued_ids.append(issued)

        return {
            "id": issued,
            "amount": amount_minor,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
        }

    async def verify_payment_signature(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> bool:
        self.verified.append(
            {"order_id": order_id, "payment_id": payment_id, "signature": signature}
        )
        if self.fail_verify is not None:
            raise self.fail_verify
        return True


__all__ = [
    "FakeRazorpay",
    "LLMUnavailable",
    "ScriptedLLM",
    "response",
    "text_block",
    "tool_use_block",
]
