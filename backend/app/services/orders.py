"""Order lifecycle: gated, audited, idempotent.

Every path that spends money runs the same sequence, and the ordering is
load-bearing:

    1. validate the product and compute the amount locally
    2. reserve the idempotency key
    3. ask `guardrails.evaluate()` for a verdict
    4. write the audit entry — BEFORE anything irreversible happens
    5. persist a local Order row
    6. only now call Razorpay, retrying once on a retryable failure
    7. update both the order and the audit entry with what happened

Steps 3-4 are why a refusal is as well-recorded as a success: a blocked order
still gets an audit row and an Order row marked BLOCKED, so the dashboard shows
what the agent was stopped from doing, not just what it did.

The gate lives here rather than in the agent because this is the single choke
point every caller passes through — the tool, the approval endpoint, and any
future path. A gate in the agent could be bypassed by calling the service.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utc_iso
from app.db.models import AuditAction, AuditLog, Order, OrderStatus, Product
from app.services import audit_logger, guardrails
from app.services.audit_logger import AuditSpan
from app.services.guardrails import GuardrailDecision
from app.services.idempotency import IN_FLIGHT, get_store
from app.services.money import format_money
from app.services.razorpay_client import RazorpayClient, RazorpayError, get_razorpay_client

logger = logging.getLogger(__name__)

MAX_QUANTITY = 20
AGENT_ID = "purchasing-agent"


class OrderError(Exception):
    """A business-rule failure, phrased for the agent to relay to the buyer."""

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


def new_order_id() -> str:
    return f"ord-{uuid.uuid4().hex[:12]}"


def receipt_for(order_id: str) -> str:
    # Razorpay caps receipt at 40 characters.
    return f"rcpt-{order_id}"[:40]


def serialise_order(order: Order) -> dict[str, Any]:
    """Agent- and UI-facing representation of an order."""
    return {
        "order_id": order.id,
        "status": order.status.value,
        "product": {"id": order.product_id, "name": order.product_name},
        "quantity": order.quantity,
        "unit_price": {
            "amount_minor": order.unit_price_minor,
            "currency": order.currency,
            "display": format_money(order.unit_price_minor, order.currency),
        },
        "total": {
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "display": format_money(order.amount_minor, order.currency),
        },
        "razorpay_order_id": order.razorpay_order_id,
        "razorpay_payment_id": order.razorpay_payment_id,
        "receipt": order.receipt,
        "conversation_id": order.conversation_id,
        "attempts": order.attempts,
        "failure": (
            {"code": order.failure_code, "reason": order.failure_reason}
            if order.failure_code
            else None
        ),
        "created_at": utc_iso(order.created_at),
    }


def _checkout_params(order: Order) -> dict[str, Any]:
    """Everything the browser needs to open Razorpay Checkout.

    The key id is the publishable half of the pair; the secret never leaves the
    server.
    """
    return {
        "key_id": settings.razorpay_key_id,
        "razorpay_order_id": order.razorpay_order_id,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "name": settings.app_name,
        "description": f"{order.quantity} x {order.product_name}",
    }


async def _load_purchasable_product(
    session: AsyncSession, product_id: str, quantity: int
) -> Product:
    """Fetch a product and assert it can actually be bought right now."""
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise OrderError(
            "invalid_quantity",
            f"Quantity must be between 1 and {MAX_QUANTITY}, got {quantity}.",
        )

    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise OrderError(
            "product_not_found",
            f"No purchasable product with id {product_id!r}. "
            "Use search_catalog to find valid ids.",
            details={"product_id": product_id},
        )

    if product.stock < quantity:
        raise OrderError(
            "insufficient_stock",
            f"Only {product.stock} unit(s) of {product.name!r} are in stock; "
            f"{quantity} {'was' if quantity == 1 else 'were'} requested.",
            details={"product_id": product_id, "available": product.stock},
        )

    return product


async def _place_with_provider(
    session: AsyncSession,
    order: Order,
    span: AuditSpan,
    client: RazorpayClient,
) -> dict[str, Any]:
    """Create the Razorpay order, retrying once on a retryable failure.

    Only *retryable* errors are retried. A rejected request is deterministic —
    retrying it burns time and produces the same failure. Attempts are counted
    on both the order and the audit entry, so a retry is visible in the trail
    rather than looking like a single clean call.
    """
    attempts = max(1, settings.provider_max_attempts)
    delay = settings.provider_retry_base_delay
    last_error: RazorpayError | None = None

    for attempt in range(1, attempts + 1):
        order.attempts += 1
        await audit_logger.record_attempt(session, span)

        try:
            return await client.create_order(
                amount_minor=order.amount_minor,
                currency=order.currency,
                receipt=order.receipt,
                notes={
                    "order_id": order.id,
                    "product_id": order.product_id,
                    "quantity": str(order.quantity),
                    "conversation_id": order.conversation_id or "",
                    "agent": order.agent_id,
                    "audit_id": span.id,
                },
            )
        except RazorpayError as exc:
            last_error = exc
            if not exc.retryable or attempt == attempts:
                raise
            logger.warning(
                "Order %s attempt %s/%s failed (%s); retrying in %.2fs",
                order.id,
                attempt,
                attempts,
                exc.code,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

    raise last_error or RazorpayError("provider_error", "Order creation failed.")


async def _execute(
    session: AsyncSession,
    order: Order,
    span: AuditSpan,
    client: RazorpayClient,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Run the provider call and settle both the order and the audit entry."""
    store = get_store()

    try:
        rzp = await _place_with_provider(session, order, span, client)
    except RazorpayError as exc:
        order.status = OrderStatus.FAILED
        order.failure_code = exc.code
        order.failure_reason = exc.message
        await session.commit()
        await audit_logger.failed(
            session, span, code=exc.code, reason=exc.message, order_id=order.id
        )
        # Release the key so a genuine retry can proceed: nothing was charged.
        if idempotency_key:
            await store.release(idempotency_key)

        logger.warning("Order %s failed after %s attempt(s)", order.id, order.attempts)
        raise OrderError(
            exc.code,
            exc.message,
            retryable=exc.retryable,
            details={"order_id": order.id, "attempts": order.attempts},
        ) from exc

    order.razorpay_order_id = str(rzp.get("id", "")) or None
    order.status = OrderStatus.AWAITING_PAYMENT
    order.failure_code = None
    order.failure_reason = None
    await session.commit()
    await session.refresh(order)

    await audit_logger.succeeded(session, span, order_id=order.id)
    if idempotency_key:
        await store.record(idempotency_key, order.id)

    logger.info("Order %s created at Razorpay as %s", order.id, order.razorpay_order_id)

    return {**serialise_order(order), "checkout": _checkout_params(order)}


async def create_order(
    session: AsyncSession,
    *,
    product_id: str,
    quantity: int = 1,
    conversation_id: str | None = None,
    idempotency_key: str | None = None,
    client: RazorpayClient | None = None,
) -> dict[str, Any]:
    """Create an order, subject to the spend guardrails."""
    client = client or get_razorpay_client()
    store = get_store()

    # ---- 1. idempotency -------------------------------------------------
    if idempotency_key:
        existing_value = await store.get(idempotency_key)
        if existing_value == IN_FLIGHT:
            raise OrderError(
                "order_in_progress",
                "An identical order is already being placed. Wait for it to "
                "finish rather than creating a second one.",
                retryable=True,
            )
        if existing_value:
            replayed = await session.get(Order, existing_value)
            if replayed is not None:
                logger.info("Idempotent replay of %s -> %s", idempotency_key, replayed.id)
                payload = {"idempotent_replay": True, **serialise_order(replayed)}
                if replayed.razorpay_order_id:
                    payload["checkout"] = _checkout_params(replayed)
                return payload

        # The database index is the backstop if the store was flushed.
        prior = (
            await session.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if prior is not None:
            return {"idempotent_replay": True, **serialise_order(prior)}

        await store.reserve(idempotency_key)

    try:
        product = await _load_purchasable_product(session, product_id, quantity)
    except OrderError:
        if idempotency_key:
            await store.release(idempotency_key)
        raise

    amount_minor = product.price_minor * quantity

    # ---- 2. the gate ----------------------------------------------------
    decision = await guardrails.evaluate(
        session, amount_minor=amount_minor, currency=product.currency, agent_id=AGENT_ID
    )

    # ---- 3. audit, before anything irreversible -------------------------
    span = await audit_logger.begin(
        session,
        action=AuditAction.CREATE_ORDER,
        decision=decision,
        agent_id=AGENT_ID,
        conversation_id=conversation_id,
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        idempotency_key=idempotency_key,
    )

    # ---- 4. the order row -----------------------------------------------
    order = Order(
        id=new_order_id(),
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        unit_price_minor=product.price_minor,
        amount_minor=amount_minor,
        currency=product.currency,
        status=OrderStatus.CREATED,
        conversation_id=conversation_id,
        agent_id=AGENT_ID,
        grant_id=decision.grant_id,
        receipt=receipt_for(new_order_id()),
        idempotency_key=idempotency_key,
        attempts=0,
        notes={"product_id": product.id, "quantity": quantity, "audit_id": span.id},
    )
    order.receipt = receipt_for(order.id)

    if decision.blocked:
        # Recorded, not merely refused: the dashboard must show what the agent
        # was stopped from doing, not only what it managed to do.
        order.status = OrderStatus.BLOCKED
        order.failure_code = "spend_blocked"
        order.failure_reason = decision.reason
        session.add(order)
        await session.commit()
        await audit_logger.attach_order(session, span, order.id)
        if idempotency_key:
            await store.release(idempotency_key)

        raise OrderError(
            "spend_blocked",
            decision.reason,
            details={
                "order_id": order.id,
                "audit_id": span.id,
                "guardrail": decision.to_payload(),
            },
        )

    if decision.needs_approval:
        order.status = OrderStatus.PENDING_APPROVAL
        session.add(order)
        await session.commit()
        await audit_logger.attach_order(session, span, order.id)
        if idempotency_key:
            await store.record(idempotency_key, order.id)

        logger.info(
            "Order %s held for approval (%s)", order.id, format_money(amount_minor, order.currency)
        )
        return {
            **serialise_order(order),
            "approval_required": True,
            "audit_id": span.id,
            "guardrail": decision.to_payload(),
        }

    session.add(order)
    await session.commit()
    await audit_logger.attach_order(session, span, order.id)

    return {
        **(await _execute(session, order, span, client, idempotency_key)),
        "audit_id": span.id,
        "guardrail": decision.to_payload(),
    }


async def approve_order(
    session: AsyncSession,
    *,
    order_id: str,
    approved_by: str = "buyer",
    client: RazorpayClient | None = None,
) -> dict[str, Any]:
    """Execute an order a human has explicitly approved.

    Approval is granted here, against a specific order id — never by the model
    reading "yes" in the chat. A confirmation the agent can infer from
    conversation text is one a prompt injection can forge.
    """
    client = client or get_razorpay_client()

    order = await session.get(Order, order_id)
    if order is None:
        raise OrderError("order_not_found", f"No order with id {order_id!r}.")

    if order.status is not OrderStatus.PENDING_APPROVAL:
        raise OrderError(
            "not_awaiting_approval",
            f"Order {order_id} is {order.status.value}, not awaiting approval.",
            details={"order_id": order_id, "status": order.status.value},
        )

    entry = await audit_logger.entry_for_order(
        session, order_id, action=AuditAction.CREATE_ORDER
    )
    if entry is None:  # pragma: no cover — begin() always writes one
        raise OrderError("audit_missing", f"No audit entry for order {order_id!r}.")

    # Re-evaluate the caps at approval time. The buyer may have approved slowly,
    # and other spend may have landed in between — an approval is permission for
    # an amount, not a bypass of the daily cap.
    recheck = await guardrails.evaluate(
        session, amount_minor=order.amount_minor, currency=order.currency, agent_id=AGENT_ID
    )
    if recheck.blocked:
        # Includes the authority check, so revoking while an order waits for
        # approval makes approving it fail rather than quietly succeed.
        order.status = OrderStatus.BLOCKED
        order.failure_code = "spend_blocked"
        order.failure_reason = recheck.reason
        await session.commit()
        entry.checks = recheck.checks_as_json()
        entry.reason = recheck.reason
        await audit_logger.declined(
            session, entry, declined_by="guardrails", reason=recheck.reason
        )
        raise OrderError(
            "spend_blocked",
            recheck.reason,
            details={"order_id": order.id, "guardrail": recheck.to_payload()},
        )

    await audit_logger.approved(session, entry, approved_by=approved_by)

    order.status = OrderStatus.CREATED
    await session.commit()

    span = AuditSpan(entry)
    payload = await _execute(session, order, span, client, order.idempotency_key)
    return {**payload, "audit_id": entry.id, "approved_by": approved_by}


async def decline_order(
    session: AsyncSession,
    *,
    order_id: str,
    declined_by: str = "buyer",
    reason: str = "Declined by the buyer.",
) -> dict[str, Any]:
    """Record that a human refused a gated order."""
    order = await session.get(Order, order_id)
    if order is None:
        raise OrderError("order_not_found", f"No order with id {order_id!r}.")

    if order.status is not OrderStatus.PENDING_APPROVAL:
        raise OrderError(
            "not_awaiting_approval",
            f"Order {order_id} is {order.status.value}, not awaiting approval.",
        )

    order.status = OrderStatus.CANCELLED
    order.failure_code = "declined"
    order.failure_reason = reason
    await session.commit()

    entry = await audit_logger.entry_for_order(
        session, order_id, action=AuditAction.CREATE_ORDER
    )
    if entry is not None:
        await audit_logger.declined(session, entry, declined_by=declined_by, reason=reason)

    if order.idempotency_key:
        await get_store().release(order.idempotency_key)

    return serialise_order(order)


async def verify_payment(
    session: AsyncSession,
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    client: RazorpayClient | None = None,
) -> dict[str, Any]:
    """Verify a completed payment's signature and settle the order."""
    client = client or get_razorpay_client()

    order = (
        await session.execute(
            select(Order).where(Order.razorpay_order_id == razorpay_order_id)
        )
    ).scalar_one_or_none()

    if order is None:
        raise OrderError(
            "order_not_found",
            f"No local order matches Razorpay order {razorpay_order_id!r}.",
            details={"razorpay_order_id": razorpay_order_id},
        )

    if order.status is OrderStatus.PAID:
        # Re-verification must stay idempotent: Razorpay can deliver both a
        # checkout callback and a webhook for the same payment.
        return {"already_settled": True, **serialise_order(order)}

    # Settling is a money action, so it is audited like one. No new spend is
    # authorised, so the decision is a trivial allow — but the outcome, and any
    # signature failure, belongs in the same trail as everything else.
    decision = GuardrailDecision(
        verdict="allow",
        reason="Settlement of an already-authorised order; no new spend.",
        amount_minor=order.amount_minor,
        currency=order.currency,
    )
    span = await audit_logger.begin(
        session,
        action=AuditAction.VERIFY_PAYMENT,
        decision=decision,
        agent_id=AGENT_ID,
        conversation_id=order.conversation_id,
        order_id=order.id,
        product_id=order.product_id,
        product_name=order.product_name,
        quantity=order.quantity,
    )
    await audit_logger.record_attempt(session, span)

    try:
        await client.verify_payment_signature(
            order_id=razorpay_order_id,
            payment_id=razorpay_payment_id,
            signature=razorpay_signature,
        )
    except RazorpayError as exc:
        order.status = OrderStatus.FAILED
        order.failure_code = exc.code
        order.failure_reason = exc.message
        await session.commit()
        await audit_logger.failed(session, span, code=exc.code, reason=exc.message)
        raise OrderError(
            exc.code, exc.message, retryable=exc.retryable, details={"order_id": order.id}
        ) from exc

    order.razorpay_payment_id = razorpay_payment_id
    order.razorpay_signature = razorpay_signature
    order.status = OrderStatus.PAID
    order.failure_code = None
    order.failure_reason = None

    # Stock is decremented only once payment is verified, so an abandoned
    # checkout never silently consumes inventory.
    product = await session.get(Product, order.product_id)
    if product is not None:
        product.stock = max(0, product.stock - order.quantity)

    await session.commit()
    await session.refresh(order)
    await audit_logger.succeeded(session, span)

    logger.info("Order %s settled as PAID (payment %s)", order.id, razorpay_payment_id)
    return serialise_order(order)


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    return await session.get(Order, order_id)


async def list_orders(session: AsyncSession, *, limit: int = 100) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def pending_approvals(session: AsyncSession) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.PENDING_APPROVAL)
        .order_by(Order.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "AuditLog",
    "MAX_QUANTITY",
    "OrderError",
    "approve_order",
    "create_order",
    "decline_order",
    "get_order",
    "list_orders",
    "pending_approvals",
    "serialise_order",
    "verify_payment",
]
