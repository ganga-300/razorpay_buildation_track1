"""Order API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.catalog import Money


class OrderProduct(BaseModel):
    id: str
    name: str


class OrderFailure(BaseModel):
    code: str | None = None
    reason: str | None = None


class OrderResponse(BaseModel):
    """One order, as the dashboard and the agent both see it."""

    order_id: str
    status: str
    product: OrderProduct
    quantity: int
    unit_price: Money
    total: Money
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    receipt: str
    conversation_id: str | None = None
    attempts: int = 0
    failure: OrderFailure | None = None
    created_at: datetime | None = None


class OrderSummary(BaseModel):
    """Aggregate figures for the dashboard header.

    `settled_total` counts only PAID orders — money that actually moved. Orders
    still awaiting payment are intent, not spend, and conflating the two would
    make the dashboard overstate what the agent has done.
    """

    total_orders: int
    by_status: dict[str, int]
    settled_total: Money
    pending_total: Money


class OrderListResponse(BaseModel):
    """`GET /orders`."""

    count: int
    summary: OrderSummary
    orders: list[OrderResponse]


class VerifyPaymentRequest(BaseModel):
    """The three values Razorpay Checkout hands back."""

    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


class VerifyPaymentResponse(BaseModel):
    verified: bool
    order: OrderResponse
