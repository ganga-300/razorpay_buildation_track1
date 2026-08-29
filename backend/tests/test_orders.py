"""Order service and money-tool tests.

Every test here runs against the fake Razorpay client — no network, no spend.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderStatus, Product
from app.services.orders import OrderError, create_order, verify_payment
from app.services.razorpay_client import RazorpayError
from app.tools import execute_tool
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


async def test_create_order_sends_the_catalog_price_in_minor_units(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """The amount charged comes from the catalog, never from the caller."""
    result = await create_order(db_session, product_id="prd-mouse", quantity=2)

    assert fake_razorpay.created == [
        {
            "amount_minor": 259_800,  # 129900 x 2
            "currency": "INR",
            "receipt": result["receipt"],
            "notes": fake_razorpay.created[0]["notes"],
        }
    ]
    assert result["total"]["amount_minor"] == 259_800
    assert result["total"]["display"] == "₹2,598.00"
    assert result["status"] == OrderStatus.AWAITING_PAYMENT.value


async def test_create_order_persists_before_calling_the_provider(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await create_order(db_session, product_id="prd-mouse", quantity=1)

    order = await db_session.get(Order, result["order_id"])
    assert order is not None
    assert order.razorpay_order_id == fake_razorpay.order_id
    assert order.unit_price_minor == 129_900
    assert order.amount_minor == 129_900
    assert order.attempts == 1


async def test_create_order_returns_checkout_parameters(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await create_order(db_session, product_id="prd-cable", quantity=1)
    checkout = result["checkout"]
    assert checkout["razorpay_order_id"] == fake_razorpay.order_id
    assert checkout["amount_minor"] == 34_900
    assert checkout["currency"] == "INR"


async def test_order_carries_the_conversation_it_came_from(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await create_order(
        db_session, product_id="prd-cable", quantity=1, conversation_id="conv-xyz"
    )
    order = await db_session.get(Order, result["order_id"])
    assert order is not None
    assert order.conversation_id == "conv-xyz"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


async def test_unknown_product_cannot_be_ordered(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-nope", quantity=1)
    assert exc.value.code == "product_not_found"
    assert fake_razorpay.created == []  # provider never contacted


async def test_inactive_product_cannot_be_ordered(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-retired", quantity=1)
    assert exc.value.code == "product_not_found"


async def test_ordering_more_than_stock_is_refused(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    # 6 is within MAX_QUANTITY but above the 5 units in stock, so this
    # isolates the stock rule from the quantity-range rule.
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-headphones", quantity=6)
    assert exc.value.code == "insufficient_stock"
    assert exc.value.details["available"] == 5
    assert fake_razorpay.created == []


async def test_out_of_stock_product_is_refused(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-espresso", quantity=1)
    assert exc.value.code == "insufficient_stock"


@pytest.mark.parametrize("quantity", [0, -1, 21])
async def test_invalid_quantities_are_refused(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay, quantity: int
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-cable", quantity=quantity)
    assert exc.value.code == "invalid_quantity"


# --------------------------------------------------------------------------
# Provider failure — the record must survive it
# --------------------------------------------------------------------------


async def test_provider_failure_still_leaves_an_auditable_order(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of persisting before the provider call."""
    from app.services import orders as orders_service

    failing = FakeRazorpay(
        fail_create=RazorpayError(
            "provider_unavailable", "gateway down", retryable=True
        )
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: failing)

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-mouse", quantity=1)
    assert exc.value.code == "provider_unavailable"
    assert exc.value.retryable is True

    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 1
    assert orders[0].status is OrderStatus.FAILED
    assert orders[0].failure_code == "provider_unavailable"
    assert orders[0].failure_reason == "gateway down"
    assert orders[0].razorpay_order_id is None  # provider never accepted it


async def test_a_rejected_request_is_not_marked_retryable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import orders as orders_service

    failing = FakeRazorpay(
        fail_create=RazorpayError("provider_rejected", "bad request", retryable=False)
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: failing)

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-mouse", quantity=1)
    assert exc.value.retryable is False


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


async def test_repeating_an_idempotency_key_does_not_charge_twice(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    first = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="key-1"
    )
    second = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="key-1"
    )

    assert second["idempotent_replay"] is True
    assert second["order_id"] == first["order_id"]
    assert len(fake_razorpay.created) == 1  # provider called exactly once


# --------------------------------------------------------------------------
# Payment verification
# --------------------------------------------------------------------------


async def test_verifying_a_payment_settles_the_order_and_decrements_stock(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    created = await create_order(db_session, product_id="prd-headphones", quantity=2)

    before = await db_session.get(Product, "prd-headphones")
    assert before is not None and before.stock == 5

    settled = await verify_payment(
        db_session,
        razorpay_order_id=created["razorpay_order_id"],
        razorpay_payment_id="pay_TEST123",
        razorpay_signature="sig",
    )

    assert settled["status"] == OrderStatus.PAID.value
    assert settled["razorpay_payment_id"] == "pay_TEST123"

    after = await db_session.get(Product, "prd-headphones")
    assert after is not None and after.stock == 3


async def test_stock_is_only_decremented_once_payment_verifies(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """An abandoned checkout must not silently consume inventory."""
    await create_order(db_session, product_id="prd-headphones", quantity=2)
    product = await db_session.get(Product, "prd-headphones")
    assert product is not None and product.stock == 5


async def test_reverifying_a_paid_order_is_idempotent(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """Razorpay can deliver both a checkout callback and a webhook."""
    created = await create_order(db_session, product_id="prd-headphones", quantity=1)
    args = {
        "razorpay_order_id": created["razorpay_order_id"],
        "razorpay_payment_id": "pay_TEST123",
        "razorpay_signature": "sig",
    }
    await verify_payment(db_session, **args)
    again = await verify_payment(db_session, **args)

    assert again["already_settled"] is True
    product = await db_session.get(Product, "prd-headphones")
    assert product is not None and product.stock == 4  # decremented once, not twice


async def test_a_forged_signature_fails_the_order(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad signature must be distinguishable from a declined card."""
    from app.services import orders as orders_service

    fake = FakeRazorpay()
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: fake)
    created = await create_order(db_session, product_id="prd-mouse", quantity=1)

    fake.fail_verify = RazorpayError("signature_mismatch", "bad signature")

    with pytest.raises(OrderError) as exc:
        await verify_payment(
            db_session,
            razorpay_order_id=created["razorpay_order_id"],
            razorpay_payment_id="pay_FORGED",
            razorpay_signature="nonsense",
        )
    assert exc.value.code == "signature_mismatch"

    order = await db_session.get(Order, created["order_id"])
    assert order is not None
    assert order.status is OrderStatus.FAILED
    assert order.razorpay_payment_id is None  # never recorded as paid


async def test_verifying_an_unknown_order_is_refused(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await verify_payment(
            db_session,
            razorpay_order_id="order_DOESNOTEXIST",
            razorpay_payment_id="pay_X",
            razorpay_signature="sig",
        )
    assert exc.value.code == "order_not_found"


# --------------------------------------------------------------------------
# Through the tool layer
# --------------------------------------------------------------------------


async def test_create_order_tool_returns_an_envelope(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await execute_tool(
        "create_order", db_session, {"product_id": "prd-cable", "quantity": 1}
    )
    assert result["ok"] is True
    assert result["data"]["total"]["amount_minor"] == 34_900


async def test_order_tool_failures_are_envelopes_not_exceptions(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await execute_tool(
        "create_order", db_session, {"product_id": "prd-espresso", "quantity": 1}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "insufficient_stock"


async def test_verify_payment_tool_requires_all_three_values(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await execute_tool(
        "verify_payment",
        db_session,
        {"razorpay_order_id": "order_X", "razorpay_payment_id": "", "razorpay_signature": "s"},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
    assert "razorpay_payment_id" in result["error"]["message"]
