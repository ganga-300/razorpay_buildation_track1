"""Order and payment endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.orders import create_order
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


async def test_orders_list_is_empty_before_anything_happens(
    client: AsyncClient,
) -> None:
    body = (await client.get("/orders")).json()
    assert body["count"] == 0
    assert body["orders"] == []
    assert body["summary"]["settled_total"]["amount_minor"] == 0


async def test_orders_list_returns_newest_first(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    first = await create_order(db_session, product_id="prd-cable", quantity=1)
    fake_razorpay.order_id = "order_SECOND"
    second = await create_order(db_session, product_id="prd-mouse", quantity=1)

    orders = (await client.get("/orders")).json()["orders"]
    assert [o["order_id"] for o in orders][0] == second["order_id"]
    assert first["order_id"] in {o["order_id"] for o in orders}


async def test_summary_counts_settled_and_pending_separately(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """Awaiting payment is intent, not spend — conflating them overstates spend."""
    created = await create_order(db_session, product_id="prd-cable", quantity=1)

    before = (await client.get("/orders")).json()["summary"]
    assert before["settled_total"]["amount_minor"] == 0
    assert before["pending_total"]["amount_minor"] == 34_900

    await client.post(
        "/payments/verify",
        json={
            "razorpay_order_id": created["razorpay_order_id"],
            "razorpay_payment_id": "pay_TEST1",
            "razorpay_signature": "sig",
        },
    )

    after = (await client.get("/orders")).json()["summary"]
    assert after["settled_total"]["amount_minor"] == 34_900
    assert after["pending_total"]["amount_minor"] == 0
    assert after["by_status"]["paid"] == 1


async def test_order_detail_and_404(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    created = await create_order(db_session, product_id="prd-mouse", quantity=1)

    ok = await client.get(f"/orders/{created['order_id']}")
    assert ok.status_code == 200
    assert ok.json()["total"]["display"] == "₹1,299.00"

    assert (await client.get("/orders/ord-nope")).status_code == 404


# --------------------------------------------------------------------------
# Payment verification
# --------------------------------------------------------------------------


async def test_verifying_a_payment_settles_the_order(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    created = await create_order(db_session, product_id="prd-cable", quantity=1)

    resp = await client.post(
        "/payments/verify",
        json={
            "razorpay_order_id": created["razorpay_order_id"],
            "razorpay_payment_id": "pay_TEST1",
            "razorpay_signature": "sig",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert body["order"]["status"] == "paid"


async def test_a_bad_signature_is_a_400_not_a_silent_success(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import orders as orders_service
    from app.services.razorpay_client import RazorpayError

    fake = FakeRazorpay()
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: fake)
    created = await create_order(db_session, product_id="prd-cable", quantity=1)

    fake.fail_verify = RazorpayError("signature_mismatch", "bad signature")
    resp = await client.post(
        "/payments/verify",
        json={
            "razorpay_order_id": created["razorpay_order_id"],
            "razorpay_payment_id": "pay_FORGED",
            "razorpay_signature": "nonsense",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "signature_mismatch"


async def test_verifying_an_unknown_order_is_400(client: AsyncClient) -> None:
    resp = await client.post(
        "/payments/verify",
        json={
            "razorpay_order_id": "order_NOPE",
            "razorpay_payment_id": "pay_X",
            "razorpay_signature": "sig",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "order_not_found"


async def test_blank_verification_values_are_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/payments/verify",
        json={
            "razorpay_order_id": "",
            "razorpay_payment_id": "pay_X",
            "razorpay_signature": "sig",
        },
    )
    assert resp.status_code == 422
