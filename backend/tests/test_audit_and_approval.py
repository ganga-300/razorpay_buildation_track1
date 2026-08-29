"""Audit trail, approval gate, and the graceful failure path.

This is the milestone the judging bar turns on: every money action explainable,
bounded and gated, with the audit trail and one failure handled gracefully.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    AuditAction,
    AuditDecision,
    AuditLog,
    AuditOutcome,
    Order,
    OrderStatus,
)
from app.services.orders import OrderError, approve_order, create_order, decline_order
from app.services.razorpay_client import RazorpayError
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


async def entries(session: AsyncSession) -> list[AuditLog]:
    return list(
        (await session.execute(select(AuditLog).order_by(AuditLog.created_at)))
        .scalars()
        .all()
    )


# ==========================================================================
# The audit trail is written BEFORE the action
# ==========================================================================


async def test_an_audit_entry_exists_even_when_the_provider_fails(
    db_session: AsyncSession, generous_limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason the write comes first.

    A trail written after the fact has no record of the most dangerous case —
    the one where the process died mid-charge.
    """
    from app.services import orders as orders_service

    failing = FakeRazorpay(
        fail_create=RazorpayError("provider_unavailable", "gateway down", retryable=True)
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: failing)

    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-mouse", quantity=1)

    trail = await entries(db_session)
    assert len(trail) == 1
    assert trail[0].action is AuditAction.CREATE_ORDER
    assert trail[0].decision is AuditDecision.ALLOW
    assert trail[0].outcome is AuditOutcome.FAILED
    assert trail[0].failure_code == "provider_unavailable"


async def test_a_successful_order_is_audited_end_to_end(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    result = await create_order(db_session, product_id="prd-cable", quantity=1)

    trail = await entries(db_session)
    assert len(trail) == 1
    entry = trail[0]
    assert entry.outcome is AuditOutcome.SUCCEEDED
    assert entry.order_id == result["order_id"]
    assert entry.amount_minor == 34_900
    assert entry.duration_ms is not None
    assert entry.attempts == 1


async def test_the_audit_entry_snapshots_the_bounds_it_checked(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """Recorded, not recomputed — so the trail stays truthful if caps change."""
    await create_order(db_session, product_id="prd-cable", quantity=1)

    entry = (await entries(db_session))[0]
    names = {c["name"] for c in entry.checks}
    assert names == {"per_transaction_cap", "daily_cap", "auto_approve_limit"}

    per_txn = next(c for c in entry.checks if c["name"] == "per_transaction_cap")
    assert per_txn["limit_minor"] == settings.per_transaction_cap_minor
    assert per_txn["limit_display"] == "₹2,000.00"


# ==========================================================================
# Blocked: over a hard cap
# ==========================================================================


async def test_a_capped_order_is_blocked_and_never_reaches_razorpay(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    assert exc.value.code == "spend_blocked"
    assert fake_razorpay.created == []  # the provider was never contacted


async def test_a_blocked_order_is_still_recorded(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """The dashboard must show what the agent was stopped from doing."""
    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    orders = list((await db_session.execute(select(Order))).scalars().all())
    assert len(orders) == 1
    assert orders[0].status is OrderStatus.BLOCKED
    assert orders[0].failure_code == "spend_blocked"

    entry = (await entries(db_session))[0]
    assert entry.decision is AuditDecision.BLOCK
    assert entry.outcome is AuditOutcome.BLOCKED
    assert entry.order_id == orders[0].id


async def test_a_blocked_order_explains_which_bound_stopped_it(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    guardrail = exc.value.details["guardrail"]
    failed = [c["name"] for c in guardrail["checks"] if not c["passed"]]

    # ₹2,499 breaches the cap AND sits above the auto-approve limit, so both
    # checks legitimately fail. The decisive one is the cap — it is evaluated
    # first and it is the one named in the reason, because it is the bound a
    # human cannot approve past.
    assert failed[0] == "per_transaction_cap"
    assert set(failed) == {"per_transaction_cap", "auto_approve_limit"}
    assert "per-transaction cap" in guardrail["reason"]
    assert guardrail["amount"]["display"] == "₹2,499.00"


async def test_blocked_spend_does_not_consume_the_daily_cap(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    from app.services.guardrails import spent_in_last_24h

    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    assert await spent_in_last_24h(db_session) == 0


# ==========================================================================
# The approval gate
# ==========================================================================


async def test_an_order_over_the_threshold_pauses_instead_of_executing(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    result = await create_order(db_session, product_id="prd-mouse", quantity=1)

    assert result["approval_required"] is True
    assert result["status"] == OrderStatus.PENDING_APPROVAL.value
    assert fake_razorpay.created == []  # nothing charged while it waits

    entry = (await entries(db_session))[0]
    assert entry.decision is AuditDecision.REQUIRE_APPROVAL
    assert entry.outcome is AuditOutcome.AWAITING_APPROVAL


async def test_approval_executes_the_order_and_records_who_approved(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)

    approved = await approve_order(
        db_session, order_id=held["order_id"], approved_by="ganga"
    )

    assert approved["status"] == OrderStatus.AWAITING_PAYMENT.value
    assert fake_razorpay.created[0]["amount_minor"] == 129_900

    entry = (await entries(db_session))[0]
    assert entry.approved_by == "ganga"
    assert entry.approved_at is not None
    assert entry.outcome is AuditOutcome.SUCCEEDED


async def test_declining_cancels_the_order_and_records_the_refusal(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)

    declined = await decline_order(
        db_session, order_id=held["order_id"], declined_by="ganga", reason="Too expensive"
    )

    assert declined["status"] == OrderStatus.CANCELLED.value
    assert fake_razorpay.created == []

    entry = (await entries(db_session))[0]
    assert entry.outcome is AuditOutcome.DECLINED
    assert entry.failure_reason == "Too expensive"


async def test_an_order_cannot_be_approved_twice(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)
    await approve_order(db_session, order_id=held["order_id"])

    with pytest.raises(OrderError) as exc:
        await approve_order(db_session, order_id=held["order_id"])
    assert exc.value.code == "not_awaiting_approval"
    assert len(fake_razorpay.created) == 1  # charged exactly once


async def test_a_declined_order_cannot_then_be_approved(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)
    await decline_order(db_session, order_id=held["order_id"])

    with pytest.raises(OrderError) as exc:
        await approve_order(db_session, order_id=held["order_id"])
    assert exc.value.code == "not_awaiting_approval"
    assert fake_razorpay.created == []


async def test_caps_are_rechecked_at_approval_time(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """An approval is permission for an amount, not a bypass of the daily cap.

    The buyer may approve slowly, and other spend can land in between.
    """
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)

    # Someone else's spend fills the daily window while the buyer deliberates.
    db_session.add(
        Order(
            id="ord-other-spend",
            product_id="prd-cable",
            product_name="Cable",
            quantity=1,
            unit_price_minor=980_000,
            amount_minor=980_000,
            currency="INR",
            status=OrderStatus.PAID,
            receipt="rcpt-other",
            agent_id="purchasing-agent",
        )
    )
    await db_session.commit()

    with pytest.raises(OrderError) as exc:
        await approve_order(db_session, order_id=held["order_id"])
    assert exc.value.code == "spend_blocked"
    assert fake_razorpay.created == []

    entry = (await entries(db_session))[0]
    assert entry.outcome is AuditOutcome.DECLINED
    assert entry.approved_by == "guardrails"


# ==========================================================================
# Graceful failure: retry with backoff, then a clear explanation
# ==========================================================================


class FlakyRazorpay(FakeRazorpay):
    """Fails the first N attempts, then succeeds."""

    def __init__(self, failures: int, error: RazorpayError) -> None:
        super().__init__()
        self.remaining_failures = failures
        self.error = error
        self.attempts = 0

    async def create_order(self, **kwargs):  # type: ignore[override]
        self.attempts += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise self.error
        return await super().create_order(**kwargs)


async def test_a_transient_failure_is_retried_once_and_succeeds(
    db_session: AsyncSession, generous_limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import orders as orders_service

    flaky = FlakyRazorpay(
        failures=1,
        error=RazorpayError("provider_unavailable", "gateway hiccup", retryable=True),
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: flaky)

    result = await create_order(db_session, product_id="prd-mouse", quantity=1)

    assert flaky.attempts == 2  # failed once, then succeeded
    assert result["status"] == OrderStatus.AWAITING_PAYMENT.value

    entry = (await entries(db_session))[0]
    assert entry.attempts == 2  # the retry is visible in the trail
    assert entry.outcome is AuditOutcome.SUCCEEDED


async def test_a_persistent_failure_gives_up_after_the_retry(
    db_session: AsyncSession, generous_limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import orders as orders_service

    flaky = FlakyRazorpay(
        failures=99,
        error=RazorpayError("provider_unavailable", "gateway down", retryable=True),
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: flaky)

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-mouse", quantity=1)

    assert flaky.attempts == settings.provider_max_attempts
    assert exc.value.code == "provider_unavailable"
    assert exc.value.details["attempts"] == settings.provider_max_attempts

    entry = (await entries(db_session))[0]
    assert entry.outcome is AuditOutcome.FAILED
    assert entry.attempts == settings.provider_max_attempts


async def test_a_deterministic_rejection_is_not_retried(
    db_session: AsyncSession, generous_limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retrying a bad request burns time and produces the same failure."""
    from app.services import orders as orders_service

    flaky = FlakyRazorpay(
        failures=99,
        error=RazorpayError("provider_rejected", "bad receipt", retryable=False),
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: flaky)

    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-mouse", quantity=1)

    assert flaky.attempts == 1


async def test_a_failed_order_releases_its_idempotency_key(
    db_session: AsyncSession, generous_limits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was charged, so a genuine retry must be able to proceed."""
    from app.services import orders as orders_service
    from app.services.idempotency import get_store

    flaky = FlakyRazorpay(
        failures=99,
        error=RazorpayError("provider_unavailable", "down", retryable=True),
    )
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: flaky)

    with pytest.raises(OrderError):
        await create_order(
            db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-fail"
        )

    assert await get_store().get("k-fail") is None


# ==========================================================================
# Idempotency
# ==========================================================================


async def test_an_identical_retry_returns_the_original_order(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    first = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-1"
    )
    second = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-1"
    )

    assert second["idempotent_replay"] is True
    assert second["order_id"] == first["order_id"]
    assert len(fake_razorpay.created) == 1


async def test_a_concurrent_retry_is_refused_rather_than_racing(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    from app.services.idempotency import get_store

    await get_store().reserve("k-inflight")

    with pytest.raises(OrderError) as exc:
        await create_order(
            db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-inflight"
        )
    assert exc.value.code == "order_in_progress"
    assert fake_razorpay.created == []


async def test_the_database_index_backs_up_a_flushed_store(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """Redis can be flushed or unavailable; the unique index still holds."""
    from app.services.idempotency import reset_store

    first = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-2"
    )
    reset_store()  # as if Redis lost everything

    second = await create_order(
        db_session, product_id="prd-mouse", quantity=1, idempotency_key="k-2"
    )
    assert second["order_id"] == first["order_id"]
    assert len(fake_razorpay.created) == 1


# ==========================================================================
# The API surface
# ==========================================================================


async def test_audit_endpoint_returns_the_trail_and_budget(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    await create_order(db_session, product_id="prd-cable", quantity=1)
    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    body = (await client.get("/audit")).json()
    assert body["count"] == 2
    assert body["summary"]["by_decision"] == {"allow": 1, "block": 1}
    assert body["summary"]["blocked_amount"]["amount_minor"] == 249_900
    assert body["budget"]["cap"]["amount_minor"] == settings.daily_cap_minor
    assert body["budget"]["spent"]["amount_minor"] == 34_900


async def test_audit_endpoint_filters_by_decision(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    await create_order(db_session, product_id="prd-cable", quantity=1)
    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    blocked = (await client.get("/audit", params={"decision": "block"})).json()
    assert blocked["count"] == 1
    assert blocked["entries"][0]["decision"] == "block"


async def test_audit_endpoint_filters_by_order(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    created = await create_order(db_session, product_id="prd-cable", quantity=1)
    body = (
        await client.get("/audit", params={"order_id": created["order_id"]})
    ).json()
    assert body["count"] == 1
    assert body["entries"][0]["order_id"] == created["order_id"]


async def test_approval_endpoints_drive_the_gate(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)

    pending = (await client.get("/approvals")).json()
    assert pending["count"] == 1
    assert pending["orders"][0]["order_id"] == held["order_id"]

    resp = await client.post(
        f"/orders/{held['order_id']}/approve", json={"actor": "ganga"}
    )
    assert resp.status_code == 200
    assert resp.json()["order"]["status"] == "awaiting_payment"
    assert resp.json()["approved_by"] == "ganga"

    assert (await client.get("/approvals")).json()["count"] == 0


async def test_declining_over_the_api(
    client: AsyncClient, db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    held = await create_order(db_session, product_id="prd-mouse", quantity=1)

    resp = await client.post(
        f"/orders/{held['order_id']}/decline", json={"actor": "ganga", "reason": "no"}
    )
    assert resp.status_code == 200
    assert resp.json()["order"]["status"] == "cancelled"


async def test_approving_an_order_that_is_not_gated_is_a_400(
    client: AsyncClient, db_session: AsyncSession, generous_limits: None,
    fake_razorpay: FakeRazorpay,
) -> None:
    created = await create_order(db_session, product_id="prd-cable", quantity=1)
    resp = await client.post(f"/orders/{created['order_id']}/approve")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "not_awaiting_approval"


async def test_approving_an_unknown_order_is_a_400(client: AsyncClient) -> None:
    resp = await client.post("/orders/ord-nope/approve")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "order_not_found"


# ==========================================================================
# Verification is audited too
# ==========================================================================


async def test_a_signature_failure_is_recorded_in_the_trail(
    client: AsyncClient,
    db_session: AsyncSession,
    generous_limits: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import orders as orders_service

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

    verify_entries = [
        e for e in await entries(db_session) if e.action is AuditAction.VERIFY_PAYMENT
    ]
    assert len(verify_entries) == 1
    assert verify_entries[0].outcome is AuditOutcome.FAILED
    assert verify_entries[0].failure_code == "signature_mismatch"
