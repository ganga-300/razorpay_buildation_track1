"""Spend guardrails.

Every money action passes through `evaluate()` before it executes. The result is
one of three verdicts, and each carries the full set of bounds that were checked
so the decision can be *explained*, not merely enforced:

    allow             amount is within the auto-approve limit
    require_approval  amount is above the auto-approve limit but within the caps
    block             amount breaches a hard cap; the action never runs

Two properties matter more than the arithmetic:

* **Hard caps are checked before the approval threshold.** An amount over the
  per-transaction cap is refused outright — a human cannot approve past it. If
  the order were reversed, a buyer could be prompted to authorise something the
  merchant has forbidden, and a gate a human can always click through is not a
  cap.
* **Bounds are snapshotted into the decision.** The limit and the observed value
  are recorded as they were at decision time, so the audit trail stays truthful
  after the configured caps change.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utcnow
from app.db.models import Order, OrderStatus
from app.services.money import format_money

logger = logging.getLogger(__name__)

Verdict = Literal["allow", "require_approval", "block"]

# Orders that represent real committed spend against the daily cap. An order the
# guardrails blocked, or that failed at the provider, never committed anything.
# Counting only PAID would be wrong in the other direction: a created Razorpay
# order is a live commitment, so an agent could open unlimited orders and stay
# under the cap forever.
COMMITTED_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.AWAITING_PAYMENT,
    OrderStatus.PAID,
)

DAILY_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class BoundCheck:
    """One bound, its limit, and what was actually observed against it."""

    name: str
    limit_minor: int
    observed_minor: int
    passed: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "limit_display": format_money(self.limit_minor, settings.razorpay_currency),
            "observed_display": format_money(
                self.observed_minor, settings.razorpay_currency
            ),
        }


@dataclass(frozen=True)
class GuardrailDecision:
    """The verdict, with everything needed to explain it."""

    verdict: Verdict
    reason: str
    amount_minor: int
    currency: str
    checks: list[BoundCheck] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def needs_approval(self) -> bool:
        return self.verdict == "require_approval"

    @property
    def failed_check(self) -> BoundCheck | None:
        return next((c for c in self.checks if not c.passed), None)

    def checks_as_json(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.checks]

    def to_payload(self) -> dict[str, Any]:
        """Agent- and UI-facing form of the decision."""
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "amount": {
                "amount_minor": self.amount_minor,
                "currency": self.currency,
                "display": format_money(self.amount_minor, self.currency),
            },
            "checks": self.checks_as_json(),
        }


async def spent_in_last_24h(session: AsyncSession, *, agent_id: str | None = None) -> int:
    """Committed spend in the rolling 24-hour window, in minor units."""
    since = utcnow() - DAILY_WINDOW
    stmt = select(func.coalesce(func.sum(Order.amount_minor), 0)).where(
        Order.created_at >= since,
        Order.status.in_(COMMITTED_STATUSES),
    )
    if agent_id:
        stmt = stmt.where(Order.agent_id == agent_id)
    return int((await session.execute(stmt)).scalar_one())


async def evaluate(
    session: AsyncSession,
    *,
    amount_minor: int,
    currency: str | None = None,
    agent_id: str = "purchasing-agent",
) -> GuardrailDecision:
    """Decide whether an amount may be spent, and explain why."""
    currency = currency or settings.razorpay_currency
    already_spent = await spent_in_last_24h(session, agent_id=agent_id)
    would_total = already_spent + amount_minor

    per_txn = BoundCheck(
        name="per_transaction_cap",
        limit_minor=settings.per_transaction_cap_minor,
        observed_minor=amount_minor,
        passed=amount_minor <= settings.per_transaction_cap_minor,
        description="Hard ceiling for any single order.",
    )
    daily = BoundCheck(
        name="daily_cap",
        limit_minor=settings.daily_cap_minor,
        observed_minor=would_total,
        passed=would_total <= settings.daily_cap_minor,
        description="Rolling 24-hour ceiling across all committed agent spend.",
    )
    auto_approve = BoundCheck(
        name="auto_approve_limit",
        limit_minor=settings.auto_approve_limit_minor,
        observed_minor=amount_minor,
        passed=amount_minor <= settings.auto_approve_limit_minor,
        description="At or below this, the agent may spend without asking a human.",
    )

    checks = [per_txn, daily, auto_approve]
    money = format_money(amount_minor, currency)

    # Hard caps first: a human must not be able to approve past them.
    if not per_txn.passed:
        return GuardrailDecision(
            verdict="block",
            reason=(
                f"{money} exceeds the per-transaction cap of "
                f"{format_money(per_txn.limit_minor, currency)}. This cannot be "
                "approved — it is a merchant limit, not a confirmation step."
            ),
            amount_minor=amount_minor,
            currency=currency,
            checks=checks,
        )

    if not daily.passed:
        remaining = max(0, settings.daily_cap_minor - already_spent)
        return GuardrailDecision(
            verdict="block",
            reason=(
                f"{money} would take 24-hour spend to "
                f"{format_money(would_total, currency)}, over the daily cap of "
                f"{format_money(daily.limit_minor, currency)}. "
                f"{format_money(remaining, currency)} remains today."
            ),
            amount_minor=amount_minor,
            currency=currency,
            checks=checks,
        )

    if not auto_approve.passed:
        return GuardrailDecision(
            verdict="require_approval",
            reason=(
                f"{money} is above the {format_money(auto_approve.limit_minor, currency)} "
                "auto-approve limit, so it needs explicit human approval before it runs."
            ),
            amount_minor=amount_minor,
            currency=currency,
            checks=checks,
        )

    return GuardrailDecision(
        verdict="allow",
        reason=(
            f"{money} is within the "
            f"{format_money(auto_approve.limit_minor, currency)} auto-approve limit "
            "and within both caps."
        ),
        amount_minor=amount_minor,
        currency=currency,
        checks=checks,
    )


async def budget_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Current position against the daily cap, for the dashboard meter."""
    currency = settings.razorpay_currency
    spent = await spent_in_last_24h(session)
    cap = settings.daily_cap_minor
    remaining = max(0, cap - spent)

    return {
        "window_hours": int(DAILY_WINDOW.total_seconds() // 3600),
        "currency": currency,
        "spent": {
            "amount_minor": spent,
            "currency": currency,
            "display": format_money(spent, currency),
        },
        "cap": {
            "amount_minor": cap,
            "currency": currency,
            "display": format_money(cap, currency),
        },
        "remaining": {
            "amount_minor": remaining,
            "currency": currency,
            "display": format_money(remaining, currency),
        },
        "used_fraction": min(1.0, spent / cap) if cap else 0.0,
        "auto_approve_limit": {
            "amount_minor": settings.auto_approve_limit_minor,
            "currency": currency,
            "display": format_money(settings.auto_approve_limit_minor, currency),
        },
        "per_transaction_cap": {
            "amount_minor": settings.per_transaction_cap_minor,
            "currency": currency,
            "display": format_money(settings.per_transaction_cap_minor, currency),
        },
    }
