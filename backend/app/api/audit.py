"""Audit trail and human-approval endpoints.

Approval is granted **here**, against a specific order id — never by the agent
reading "yes" in the chat transcript. A confirmation the model infers from
conversation text is one a prompt injection can forge; a POST to this endpoint
is an action only the person at the keyboard can take.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AuditAction, AuditDecision, AuditOutcome
from app.db.session import get_session
from app.schemas.audit import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuditListResponse,
    AuditSummary,
    BudgetSnapshot,
    PendingApprovalsResponse,
)
from app.schemas.catalog import Money
from app.schemas.orders import OrderResponse
from app.services import audit_logger
from app.services.guardrails import budget_snapshot
from app.services.orders import (
    OrderError,
    approve_order,
    decline_order,
    pending_approvals,
    serialise_order,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=AuditListResponse, summary="Full audit trail")
async def get_audit(
    session: AsyncSession = Depends(get_session),
    order_id: str | None = Query(default=None, description="Only entries for this order"),
    decision: AuditDecision | None = Query(default=None, description="allow / require_approval / block"),
    outcome: AuditOutcome | None = Query(default=None),
    action: AuditAction | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> AuditListResponse:
    """Every gated money decision, newest first."""
    entries = await audit_logger.list_entries(
        session,
        order_id=order_id,
        decision=decision,
        outcome=outcome,
        action=action,
        limit=limit,
    )

    currency = settings.razorpay_currency
    by_decision: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    blocked_total = approved_total = 0

    for entry in entries:
        by_decision[entry.decision.value] = by_decision.get(entry.decision.value, 0) + 1
        by_outcome[entry.outcome.value] = by_outcome.get(entry.outcome.value, 0) + 1
        if entry.decision is AuditDecision.BLOCK:
            blocked_total += entry.amount_minor
        if entry.approved_by and entry.approved_by != "guardrails":
            approved_total += entry.amount_minor

    return AuditListResponse(
        count=len(entries),
        summary=AuditSummary(
            total=len(entries),
            by_decision=by_decision,
            by_outcome=by_outcome,
            blocked_amount=Money.of(blocked_total, currency),
            approved_amount=Money.of(approved_total, currency),
        ),
        budget=BudgetSnapshot.model_validate(await budget_snapshot(session)),
        entries=[
            audit_logger.serialise(e) for e in entries  # type: ignore[misc]
        ],
    )


@router.get(
    "/approvals",
    response_model=PendingApprovalsResponse,
    summary="Orders waiting on a human",
)
async def get_pending_approvals(
    session: AsyncSession = Depends(get_session),
) -> PendingApprovalsResponse:
    orders = await pending_approvals(session)
    return PendingApprovalsResponse(
        count=len(orders),
        orders=[OrderResponse.model_validate(serialise_order(o)) for o in orders],
    )


@router.post(
    "/orders/{order_id}/approve",
    response_model=ApprovalResponse,
    summary="Approve a gated order and execute it",
    responses={400: {"description": "Not awaiting approval, or refused by a hard cap"}},
)
async def approve(
    order_id: str,
    request: ApprovalDecisionRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Authorise an order the guardrails held for human approval."""
    actor = (request or ApprovalDecisionRequest()).actor
    try:
        result = await approve_order(session, order_id=order_id, approved_by=actor)
    except OrderError as exc:
        logger.warning("Approval of %s failed: %s", order_id, exc.code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message, **exc.details},
        ) from exc

    return ApprovalResponse(
        order=OrderResponse.model_validate(result),
        audit_id=result.get("audit_id"),
        approved_by=result.get("approved_by"),
    )


@router.post(
    "/orders/{order_id}/decline",
    response_model=ApprovalResponse,
    summary="Decline a gated order",
    responses={400: {"description": "Not awaiting approval"}},
)
async def decline(
    order_id: str,
    request: ApprovalDecisionRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Refuse an order the guardrails held for human approval."""
    body = request or ApprovalDecisionRequest()
    try:
        result = await decline_order(
            session,
            order_id=order_id,
            declined_by=body.actor,
            reason=body.reason or "Declined by the buyer.",
        )
    except OrderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return ApprovalResponse(order=OrderResponse.model_validate(result))
