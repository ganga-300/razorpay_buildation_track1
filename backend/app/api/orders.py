"""Order and payment endpoints.

`POST /payments/verify` is deliberately **not** routed through the agent.
Signature verification is a security control, and a control whose execution
depends on a language model choosing to call a tool is not a control. The agent
still has a `verify_payment` tool — useful when a buyer says "I've paid" in
chat — but the checkout callback settles orders deterministically.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Order, OrderStatus
from app.db.session import get_session
from app.schemas.catalog import Money
from app.schemas.orders import (
    OrderListResponse,
    OrderResponse,
    OrderSummary,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from app.services.orders import OrderError, list_orders, serialise_order, verify_payment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orders"])


def _to_response(order: Order) -> OrderResponse:
    return OrderResponse.model_validate(serialise_order(order))


def _summarise(orders: list[Order]) -> OrderSummary:
    currency = settings.razorpay_currency
    by_status: dict[str, int] = {}
    settled = pending = 0

    for order in orders:
        by_status[order.status.value] = by_status.get(order.status.value, 0) + 1
        if order.status is OrderStatus.PAID:
            settled += order.amount_minor
        elif order.status in {OrderStatus.CREATED, OrderStatus.AWAITING_PAYMENT}:
            pending += order.amount_minor

    return OrderSummary(
        total_orders=len(orders),
        by_status=by_status,
        settled_total=Money.of(settled, currency),
        pending_total=Money.of(pending, currency),
    )


@router.get(
    "/orders",
    response_model=OrderListResponse,
    summary="All orders, newest first",
)
async def get_orders(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
) -> OrderListResponse:
    """List orders with dashboard summary figures."""
    orders = await list_orders(session, limit=limit)
    return OrderListResponse(
        count=len(orders),
        summary=_summarise(orders),
        orders=[_to_response(o) for o in orders],
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="One order",
    responses={404: {"description": "No such order"}},
)
async def get_order_detail(
    order_id: str,
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No order with id {order_id!r}",
        )
    return _to_response(order)


@router.post(
    "/payments/verify",
    response_model=VerifyPaymentResponse,
    summary="Verify a Razorpay Checkout callback and settle the order",
    responses={
        400: {"description": "Signature did not verify, or the order is unknown"}
    },
)
async def verify(
    request: VerifyPaymentRequest,
    session: AsyncSession = Depends(get_session),
) -> VerifyPaymentResponse:
    """Deterministically verify a payment signature and settle the order."""
    try:
        settled = await verify_payment(
            session,
            razorpay_order_id=request.razorpay_order_id,
            razorpay_payment_id=request.razorpay_payment_id,
            razorpay_signature=request.razorpay_signature,
        )
    except OrderError as exc:
        logger.warning("Payment verification failed: %s", exc.code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return VerifyPaymentResponse(
        verified=True, order=OrderResponse.model_validate(settled)
    )
