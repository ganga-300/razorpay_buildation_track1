"""Consent lifecycle: grant purchasing authority, then revoke it.

The spend caps in `guardrails.py` bound *how much* can move in one transaction
or one day. This bounds something different and prior: **whether the agent may
act at all**, and for how long.

The shape is the pre-authorisation pattern — a buyer approves a capped, expiring
allowance once, the agent transacts freely inside it without re-approving every
purchase, and the buyer can withdraw it instantly. Revocation is the part that
makes the rest trustworthy: an authority you cannot take back is not a grant,
it is a transfer.

Spend against a grant is **summed from the orders that reference it**, never
kept as a running counter. A counter drifts the first time an order fails
between increment and rollback; a sum cannot.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utc_iso, utcnow
from app.db.models import AgentGrant, GrantStatus, Order, OrderStatus
from app.services.money import format_money

logger = logging.getLogger(__name__)

DEFAULT_BUYER_ID = "buyer"
DEFAULT_MERCHANT_ID = "autobuy"

# Orders that consumed part of a grant. A blocked or failed order never spent
# anything, so it must not eat into the buyer's authorised allowance.
CONSUMING_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.AWAITING_PAYMENT,
    OrderStatus.PAID,
)


class GrantError(Exception):
    """A consent-lifecycle failure, phrased for a buyer to read."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def new_grant_id() -> str:
    return f"grant-{uuid.uuid4().hex[:12]}"


async def spent_under(session: AsyncSession, grant_id: str) -> int:
    """Committed spend attributed to one grant, in minor units."""
    stmt = select(func.coalesce(func.sum(Order.amount_minor), 0)).where(
        Order.grant_id == grant_id,
        Order.status.in_(CONSUMING_STATUSES),
    )
    return int((await session.execute(stmt)).scalar_one())


async def active_grant(
    session: AsyncSession, *, buyer_id: str = DEFAULT_BUYER_ID
) -> AgentGrant | None:
    """The buyer's live grant, if any.

    Expiry is evaluated here rather than by a background job: a grant that has
    run out of time must stop working the moment it does, not whenever a sweeper
    next runs.
    """
    stmt = (
        select(AgentGrant)
        .where(AgentGrant.buyer_id == buyer_id, AgentGrant.status == GrantStatus.ACTIVE)
        .order_by(AgentGrant.created_at.desc())
    )
    for grant in (await session.execute(stmt)).scalars().all():
        if grant.is_live():
            return grant
        # Lazily settle the status so the dashboard reads truthfully.
        grant.status = GrantStatus.EXPIRED
        await session.commit()
        logger.info("Grant %s expired", grant.id)
    return None


async def serialise(session: AsyncSession, grant: AgentGrant) -> dict[str, Any]:
    """API representation, including live spend against the grant."""
    spent = await spent_under(session, grant.id)
    remaining = max(0, grant.spend_cap_minor - spent)
    currency = grant.currency

    return {
        "id": grant.id,
        "buyer_id": grant.buyer_id,
        "merchant_id": grant.merchant_id,
        "agent_id": grant.agent_id,
        "status": grant.status.value,
        "is_live": grant.is_live(),
        "spend_cap": {
            "amount_minor": grant.spend_cap_minor,
            "currency": currency,
            "display": format_money(grant.spend_cap_minor, currency),
        },
        "spent": {
            "amount_minor": spent,
            "currency": currency,
            "display": format_money(spent, currency),
        },
        "remaining": {
            "amount_minor": remaining,
            "currency": currency,
            "display": format_money(remaining, currency),
        },
        "used_fraction": min(1.0, spent / grant.spend_cap_minor) if grant.spend_cap_minor else 0.0,
        "expires_at": utc_iso(grant.expires_at),
        "revoked_at": utc_iso(grant.revoked_at),
        "revoked_by": grant.revoked_by,
        "revoke_reason": grant.revoke_reason,
        "note": grant.note,
        "created_at": utc_iso(grant.created_at),
    }


async def grant_access(
    session: AsyncSession,
    *,
    spend_cap_minor: int,
    expires_in_hours: int = 24,
    buyer_id: str = DEFAULT_BUYER_ID,
    note: str | None = None,
) -> AgentGrant:
    """Authorise the agent to spend up to a cap, until an expiry.

    Any existing live grant for this buyer is revoked first. Two concurrent
    grants would mean two allowances and an ambiguous answer to "how much may
    this agent still spend" — the one question the buyer most needs answered.
    """
    if spend_cap_minor <= 0:
        raise GrantError("invalid_cap", "The spending cap must be greater than zero.")
    if expires_in_hours <= 0:
        raise GrantError("invalid_expiry", "The expiry must be in the future.")

    existing = await active_grant(session, buyer_id=buyer_id)
    if existing is not None:
        existing.status = GrantStatus.REVOKED
        existing.revoked_at = utcnow()
        existing.revoked_by = buyer_id
        existing.revoke_reason = "Superseded by a new grant."
        logger.info("Grant %s superseded", existing.id)

    grant = AgentGrant(
        id=new_grant_id(),
        buyer_id=buyer_id,
        merchant_id=DEFAULT_MERCHANT_ID,
        spend_cap_minor=spend_cap_minor,
        currency=settings.razorpay_currency,
        expires_at=utcnow() + timedelta(hours=expires_in_hours),
        status=GrantStatus.ACTIVE,
        note=note,
    )
    session.add(grant)
    await session.commit()
    await session.refresh(grant)

    from app.db.models import AuditAction
    from app.services import audit_logger

    await audit_logger.record_consent_event(
        session,
        action=AuditAction.GRANT_ACCESS,
        grant_id=grant.id,
        amount_minor=spend_cap_minor,
        currency=grant.currency,
        actor=buyer_id,
        reason=(
            f"Buyer granted the agent {format_money(spend_cap_minor, grant.currency)} "
            f"of purchasing authority, expiring in {expires_in_hours}h."
        ),
    )

    logger.info(
        "Granted %s to the agent until %s (grant %s)",
        format_money(spend_cap_minor, grant.currency),
        grant.expires_at,
        grant.id,
    )
    return grant


async def revoke_access(
    session: AsyncSession,
    *,
    grant_id: str,
    revoked_by: str = DEFAULT_BUYER_ID,
    reason: str = "Revoked by the buyer.",
) -> AgentGrant:
    """Withdraw purchasing authority, effective immediately.

    Immediately means immediately: the next `create_order` — including one the
    agent is midway through deciding on — fails the grant check and is refused.
    Nothing is cached, so there is no window in which a revoked agent can still
    spend.
    """
    grant = await session.get(AgentGrant, grant_id)
    if grant is None:
        raise GrantError("grant_not_found", f"No grant with id {grant_id!r}.")

    if grant.status is GrantStatus.REVOKED:
        return grant  # idempotent: revoking twice is not an error

    spent = await spent_under(session, grant.id)
    unused = max(0, grant.spend_cap_minor - spent)

    grant.status = GrantStatus.REVOKED
    grant.revoked_at = utcnow()
    grant.revoked_by = revoked_by
    grant.revoke_reason = reason
    await session.commit()
    await session.refresh(grant)

    from app.db.models import AuditAction
    from app.services import audit_logger

    await audit_logger.record_consent_event(
        session,
        action=AuditAction.REVOKE_ACCESS,
        grant_id=grant.id,
        # The amount withdrawn — what the agent could still have spent and now
        # cannot. That is the number a buyer cares about at the moment of revoking.
        amount_minor=unused,
        currency=grant.currency,
        actor=revoked_by,
        reason=(
            f"{reason} {format_money(unused, grant.currency)} of unspent authority "
            f"withdrawn; {format_money(spent, grant.currency)} had been used."
        ),
    )

    logger.warning("Grant %s REVOKED by %s: %s", grant_id, revoked_by, reason)
    return grant


async def list_grants(
    session: AsyncSession, *, buyer_id: str | None = None, limit: int = 50
) -> list[AgentGrant]:
    stmt = select(AgentGrant).order_by(AgentGrant.created_at.desc()).limit(limit)
    if buyer_id:
        stmt = stmt.where(AgentGrant.buyer_id == buyer_id)
    return list((await session.execute(stmt)).scalars().all())
