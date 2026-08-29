"""Spend guardrail tests.

These run against the real configured limits from `.env.example`:

    auto-approve limit      ₹500.00      (50_000 paise)
    per-transaction cap   ₹2,000.00     (200_000 paise)
    daily cap            ₹10,000.00   (1_000_000 paise)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Order, OrderStatus
from app.services import guardrails
from app.services.guardrails import evaluate, spent_in_last_24h

pytestmark = pytest.mark.asyncio


def check(decision: guardrails.GuardrailDecision, name: str) -> guardrails.BoundCheck:
    return next(c for c in decision.checks if c.name == name)


# --------------------------------------------------------------------------
# The three verdicts
# --------------------------------------------------------------------------


async def test_a_small_amount_is_allowed_outright(db_session: AsyncSession) -> None:
    decision = await evaluate(db_session, amount_minor=34_900)
    assert decision.verdict == "allow"
    assert decision.allowed is True
    assert all(c.passed for c in decision.checks)


async def test_an_amount_over_the_auto_approve_limit_needs_a_human(
    db_session: AsyncSession,
) -> None:
    decision = await evaluate(db_session, amount_minor=129_900)
    assert decision.verdict == "require_approval"
    assert check(decision, "auto_approve_limit").passed is False
    # But it is within both hard caps, which is why a human *may* authorise it.
    assert check(decision, "per_transaction_cap").passed is True
    assert check(decision, "daily_cap").passed is True


async def test_an_amount_over_the_per_transaction_cap_is_blocked(
    db_session: AsyncSession,
) -> None:
    decision = await evaluate(db_session, amount_minor=249_900)
    assert decision.verdict == "block"
    assert decision.blocked is True
    assert check(decision, "per_transaction_cap").passed is False


async def test_a_hard_cap_beats_the_approval_threshold(
    db_session: AsyncSession,
) -> None:
    """Order of evaluation matters.

    If the approval threshold were checked first, a buyer would be prompted to
    authorise an amount the merchant has forbidden — and a cap a human can click
    through is not a cap.
    """
    decision = await evaluate(db_session, amount_minor=899_900)
    assert decision.verdict == "block"
    assert "cannot be approved" in decision.reason


async def test_the_boundary_is_inclusive(db_session: AsyncSession) -> None:
    """Exactly at the limit is allowed; one paise over is not."""
    at_limit = await evaluate(db_session, amount_minor=settings.auto_approve_limit_minor)
    assert at_limit.verdict == "allow"

    over = await evaluate(db_session, amount_minor=settings.auto_approve_limit_minor + 1)
    assert over.verdict == "require_approval"

    at_cap = await evaluate(db_session, amount_minor=settings.per_transaction_cap_minor)
    assert at_cap.verdict == "require_approval"  # within the cap, over auto-approve

    over_cap = await evaluate(
        db_session, amount_minor=settings.per_transaction_cap_minor + 1
    )
    assert over_cap.verdict == "block"


# --------------------------------------------------------------------------
# The daily cap
# --------------------------------------------------------------------------


async def _commit_spend(session: AsyncSession, amount: int, status: OrderStatus) -> None:
    session.add(
        Order(
            id=f"ord-seed-{amount}-{status.value}",
            product_id="prd-cable",
            product_name="Cable",
            quantity=1,
            unit_price_minor=amount,
            amount_minor=amount,
            currency="INR",
            status=status,
            receipt="rcpt-seed",
            agent_id="purchasing-agent",
        )
    )
    await session.commit()


async def test_committed_spend_counts_toward_the_daily_cap(
    db_session: AsyncSession,
) -> None:
    await _commit_spend(db_session, 400_000, OrderStatus.PAID)
    assert await spent_in_last_24h(db_session) == 400_000


async def test_awaiting_payment_counts_as_committed(db_session: AsyncSession) -> None:
    """A created Razorpay order is a live commitment.

    Counting only PAID would let the agent open unlimited orders and stay under
    the cap forever.
    """
    await _commit_spend(db_session, 300_000, OrderStatus.AWAITING_PAYMENT)
    assert await spent_in_last_24h(db_session) == 300_000


@pytest.mark.parametrize(
    "status", [OrderStatus.BLOCKED, OrderStatus.FAILED, OrderStatus.CANCELLED]
)
async def test_uncommitted_orders_do_not_consume_the_daily_cap(
    db_session: AsyncSession, status: OrderStatus
) -> None:
    """A refused or failed order never spent anything."""
    await _commit_spend(db_session, 900_000, status)
    assert await spent_in_last_24h(db_session) == 0


async def test_the_daily_cap_blocks_once_the_window_is_full(
    db_session: AsyncSession,
) -> None:
    await _commit_spend(db_session, 950_000, OrderStatus.PAID)

    decision = await evaluate(db_session, amount_minor=100_000)
    assert decision.verdict == "block"
    assert check(decision, "daily_cap").passed is False
    # The reason tells the buyer what headroom is left, not just that it failed.
    assert "₹500.00 remains today" in decision.reason


async def test_the_daily_cap_check_uses_the_running_total_not_the_amount(
    db_session: AsyncSession,
) -> None:
    await _commit_spend(db_session, 600_000, OrderStatus.PAID)
    decision = await evaluate(db_session, amount_minor=40_000)
    assert check(decision, "daily_cap").observed_minor == 640_000


# --------------------------------------------------------------------------
# Explainability
# --------------------------------------------------------------------------


async def test_every_decision_reports_all_three_bounds(
    db_session: AsyncSession,
) -> None:
    """A decision must be explainable, not just correct."""
    for amount in (10_000, 129_900, 249_900):
        decision = await evaluate(db_session, amount_minor=amount)
        assert {c.name for c in decision.checks} == {
            "per_transaction_cap",
            "daily_cap",
            "auto_approve_limit",
        }


async def test_the_decision_payload_carries_displayable_amounts(
    db_session: AsyncSession,
) -> None:
    payload = (await evaluate(db_session, amount_minor=249_900)).to_payload()
    assert payload["amount"]["display"] == "₹2,499.00"
    limits = {c["name"]: c["limit_display"] for c in payload["checks"]}
    assert limits["per_transaction_cap"] == "₹2,000.00"
    assert limits["auto_approve_limit"] == "₹500.00"


async def test_budget_snapshot_reports_headroom(db_session: AsyncSession) -> None:
    await _commit_spend(db_session, 250_000, OrderStatus.PAID)
    snap = await guardrails.budget_snapshot(db_session)

    assert snap["spent"]["amount_minor"] == 250_000
    assert snap["remaining"]["amount_minor"] == 750_000
    assert snap["used_fraction"] == pytest.approx(0.25)
    assert snap["window_hours"] == 24
