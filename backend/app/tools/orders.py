"""Money-moving tools exposed to the purchasing agent.

Both tools are registered with ``mutates_money=True``. In Milestone 2 that flag
is only metadata; in Milestone 4 the agent's ``create_order`` node reads it to
decide that a call must pass `services/guardrails.py` and be written to the
audit trail before it executes. Registering the flag now means the gate cannot
be forgotten later — a money tool that lacks it will fail the registry test.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.orders import MAX_QUANTITY, OrderError
from app.services.orders import create_order as _create_order
from app.services.orders import verify_payment as _verify_payment
from app.tools.base import ToolError, ToolSpec, registry

CREATE_ORDER_DESCRIPTION = """\
Create a Razorpay order for a product the buyer has agreed to purchase.

Call this ONLY after the buyer has clearly confirmed they want to buy a specific \
product. Do not call it to check a price or to explore options — use \
search_catalog or get_product for that.

The total is computed server-side from the catalog price; you do not pass an \
amount. The merchant's spend caps are enforced server-side, so this call can be \
refused even when the buyer agreed — if it is, tell the buyer plainly what limit \
was hit and what they can do instead.

Returns the order and the checkout parameters the buyer needs to pay."""

VERIFY_PAYMENT_DESCRIPTION = """\
Verify a completed payment's signature and settle the order.

Call this after the buyer has paid and you have the three Razorpay values from \
checkout. A signature that does not verify means the payment cannot be trusted; \
report that to the buyer rather than treating it as success."""


def _as_tool_error(exc: OrderError) -> ToolError:
    """Order failures reach the model as handled envelopes, never exceptions."""
    return ToolError(exc.code, exc.message, retryable=exc.retryable, details=exc.details)


async def create_order(
    session: AsyncSession,
    product_id: str,
    quantity: int = 1,
    conversation_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create an order for `quantity` units of `product_id`."""
    if not product_id or not product_id.strip():
        raise ToolError("invalid_arguments", "product_id is required")

    try:
        return await _create_order(
            session,
            product_id=product_id.strip(),
            quantity=quantity,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    except OrderError as exc:
        raise _as_tool_error(exc) from exc


async def verify_payment(
    session: AsyncSession,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict[str, Any]:
    """Verify a payment signature and settle the matching order."""
    missing = [
        name
        for name, value in (
            ("razorpay_order_id", razorpay_order_id),
            ("razorpay_payment_id", razorpay_payment_id),
            ("razorpay_signature", razorpay_signature),
        )
        if not value or not value.strip()
    ]
    if missing:
        raise ToolError(
            "invalid_arguments", f"Missing required values: {', '.join(missing)}"
        )

    try:
        return await _verify_payment(
            session,
            razorpay_order_id=razorpay_order_id.strip(),
            razorpay_payment_id=razorpay_payment_id.strip(),
            razorpay_signature=razorpay_signature.strip(),
        )
    except OrderError as exc:
        raise _as_tool_error(exc) from exc


registry.register(
    ToolSpec(
        name="create_order",
        description=CREATE_ORDER_DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "Exact product id from the catalog, e.g. 'prd-wireless-mouse'.",
                },
                "quantity": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_QUANTITY,
                    "description": f"Units to buy, 1 to {MAX_QUANTITY}. Defaults to 1.",
                },
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
        handler=create_order,
        mutates_money=True,
    )
)

registry.register(
    ToolSpec(
        name="verify_payment",
        description=VERIFY_PAYMENT_DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {
                "razorpay_order_id": {
                    "type": "string",
                    "description": "The 'order_...' id returned by create_order.",
                },
                "razorpay_payment_id": {
                    "type": "string",
                    "description": "The 'pay_...' id returned by Razorpay Checkout.",
                },
                "razorpay_signature": {
                    "type": "string",
                    "description": "The HMAC signature returned by Razorpay Checkout.",
                },
            },
            "required": [
                "razorpay_order_id",
                "razorpay_payment_id",
                "razorpay_signature",
            ],
            "additionalProperties": False,
        },
        handler=verify_payment,
        mutates_money=True,
    )
)
