"""Audit trail.

The contract is simple and strict: an entry is written **before** a money action
executes and updated **after** it finishes. Nothing that touches money is
allowed to run without a row already committed for it.

The reason the write comes first is failure. If the process dies mid-charge, an
audit trail written afterwards has no record at all — the most dangerous case
produces the least evidence. Writing first inverts that: an entry left in
`PENDING` is itself the finding.

Entries are committed on their own, separately from the business transaction, so
a rollback of the order cannot take the evidence with it.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import AuditAction, AuditDecision, AuditLog, AuditOutcome
from app.services.guardrails import GuardrailDecision
from app.services.money import format_money

logger = logging.getLogger(__name__)

DECISION_TO_MODEL: dict[str, AuditDecision] = {
    "allow": AuditDecision.ALLOW,
    "require_approval": AuditDecision.REQUIRE_APPROVAL,
    "block": AuditDecision.BLOCK,
}


def new_audit_id() -> str:
    return f"aud-{uuid.uuid4().hex[:12]}"


class AuditSpan:
    """Handle to an open audit entry. Records elapsed time on completion."""

    def __init__(self, entry: AuditLog) -> None:
        self.entry = entry
        self._started = time.monotonic()

    @property
    def id(self) -> str:
        return self.entry.id

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)


async def begin(
    session: AsyncSession,
    *,
    action: AuditAction,
    decision: GuardrailDecision,
    agent_id: str = "purchasing-agent",
    conversation_id: str | None = None,
    order_id: str | None = None,
    product_id: str | None = None,
    product_name: str | None = None,
    quantity: int | None = None,
    idempotency_key: str | None = None,
) -> AuditSpan:
    """Write the pre-execution record and commit it immediately."""
    verdict = decision.verdict
    outcome = {
        "block": AuditOutcome.BLOCKED,
        "require_approval": AuditOutcome.AWAITING_APPROVAL,
        "allow": AuditOutcome.PENDING,
    }[verdict]

    entry = AuditLog(
        id=new_audit_id(),
        agent_id=agent_id,
        action=action,
        decision=DECISION_TO_MODEL[verdict],
        outcome=outcome,
        conversation_id=conversation_id,
        order_id=order_id,
        product_id=product_id,
        product_name=product_name,
        quantity=quantity,
        amount_minor=decision.amount_minor,
        currency=decision.currency,
        checks=decision.checks_as_json(),
        reason=decision.reason,
        idempotency_key=idempotency_key,
        attempts=0,
    )
    session.add(entry)

    # Committed on its own: the evidence must survive a rollback of the order.
    await session.commit()

    logger.info(
        "AUDIT %s %s decision=%s amount=%s %s",
        entry.id,
        action.value,
        verdict,
        format_money(decision.amount_minor, decision.currency),
        decision.reason,
    )
    return AuditSpan(entry)


async def attach_order(session: AsyncSession, span: AuditSpan, order_id: str) -> None:
    """Link an entry to the order it produced, once the id exists."""
    span.entry.order_id = order_id
    await session.commit()


async def record_attempt(session: AsyncSession, span: AuditSpan) -> None:
    """Count a provider attempt, so retries are visible in the trail."""
    span.entry.attempts += 1
    await session.commit()


async def succeeded(
    session: AsyncSession, span: AuditSpan, *, order_id: str | None = None
) -> None:
    span.entry.outcome = AuditOutcome.SUCCEEDED
    span.entry.duration_ms = span._elapsed_ms()
    if order_id:
        span.entry.order_id = order_id
    await session.commit()
    logger.info("AUDIT %s outcome=succeeded in %sms", span.id, span.entry.duration_ms)


async def failed(
    session: AsyncSession,
    span: AuditSpan,
    *,
    code: str,
    reason: str,
    order_id: str | None = None,
) -> None:
    span.entry.outcome = AuditOutcome.FAILED
    span.entry.failure_code = code
    span.entry.failure_reason = reason
    span.entry.duration_ms = span._elapsed_ms()
    if order_id:
        span.entry.order_id = order_id
    await session.commit()
    logger.warning("AUDIT %s outcome=failed code=%s: %s", span.id, code, reason)


async def approved(
    session: AsyncSession, entry: AuditLog, *, approved_by: str
) -> None:
    """Record that a human authorised a gated action."""
    entry.approved_by = approved_by
    entry.approved_at = utcnow()
    entry.outcome = AuditOutcome.PENDING  # now executing
    await session.commit()
    logger.info("AUDIT %s approved by %s", entry.id, approved_by)


async def declined(
    session: AsyncSession, entry: AuditLog, *, declined_by: str, reason: str
) -> None:
    entry.outcome = AuditOutcome.DECLINED
    entry.approved_by = declined_by
    entry.approved_at = utcnow()
    entry.failure_reason = reason
    await session.commit()
    logger.info("AUDIT %s declined by %s", entry.id, declined_by)


async def entry_for_order(
    session: AsyncSession, order_id: str, *, action: AuditAction | None = None
) -> AuditLog | None:
    """Most recent entry for an order."""
    stmt = select(AuditLog).where(AuditLog.order_id == order_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_entries(
    session: AsyncSession,
    *,
    order_id: str | None = None,
    decision: AuditDecision | None = None,
    outcome: AuditOutcome | None = None,
    action: AuditAction | None = None,
    limit: int = 200,
) -> list[AuditLog]:
    """The audit trail, newest first, optionally filtered."""
    stmt = select(AuditLog)
    if order_id:
        stmt = stmt.where(AuditLog.order_id == order_id)
    if decision is not None:
        stmt = stmt.where(AuditLog.decision == decision)
    if outcome is not None:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)

    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


def serialise(entry: AuditLog) -> dict[str, Any]:
    """API representation of an audit entry."""
    return {
        "id": entry.id,
        "agent_id": entry.agent_id,
        "action": entry.action.value,
        "decision": entry.decision.value,
        "outcome": entry.outcome.value,
        "conversation_id": entry.conversation_id,
        "order_id": entry.order_id,
        "product": (
            {"id": entry.product_id, "name": entry.product_name}
            if entry.product_id
            else None
        ),
        "quantity": entry.quantity,
        "amount": {
            "amount_minor": entry.amount_minor,
            "currency": entry.currency,
            "display": format_money(entry.amount_minor, entry.currency),
        },
        "checks": entry.checks or [],
        "reason": entry.reason,
        "approved_by": entry.approved_by,
        "approved_at": entry.approved_at.isoformat() if entry.approved_at else None,
        "failure": (
            {"code": entry.failure_code, "reason": entry.failure_reason}
            if entry.failure_code or entry.failure_reason
            else None
        ),
        "attempts": entry.attempts,
        "duration_ms": entry.duration_ms,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
