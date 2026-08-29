"""Audit trail API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.catalog import Money
from app.schemas.orders import OrderProduct, OrderResponse


class BoundCheckResponse(BaseModel):
    """One bound as it was evaluated, with the values seen at that moment."""

    name: str
    limit_minor: int
    observed_minor: int
    passed: bool
    description: str
    limit_display: str
    observed_display: str


class AuditFailure(BaseModel):
    code: str | None = None
    reason: str | None = None


class AuditEntryResponse(BaseModel):
    """One recorded money action."""

    id: str
    agent_id: str
    action: str
    decision: str
    outcome: str
    conversation_id: str | None = None
    order_id: str | None = None
    product: OrderProduct | None = None
    quantity: int | None = None
    amount: Money
    checks: list[BoundCheckResponse] = Field(default_factory=list)
    reason: str
    approved_by: str | None = None
    approved_at: str | None = None
    failure: AuditFailure | None = None
    attempts: int
    duration_ms: int | None = None
    created_at: str | None = None


class AuditSummary(BaseModel):
    """Counts across the trail, for the dashboard header."""

    total: int
    by_decision: dict[str, int]
    by_outcome: dict[str, int]
    blocked_amount: Money = Field(
        description="Total the guardrails refused to spend"
    )
    approved_amount: Money = Field(
        description="Total a human explicitly authorised"
    )


class BudgetSnapshot(BaseModel):
    """Position against the rolling daily cap."""

    window_hours: int
    currency: str
    spent: Money
    cap: Money
    remaining: Money
    used_fraction: float
    auto_approve_limit: Money
    per_transaction_cap: Money


class AuditListResponse(BaseModel):
    """`GET /audit`."""

    count: int
    summary: AuditSummary
    budget: BudgetSnapshot
    entries: list[AuditEntryResponse]


class ApprovalDecisionRequest(BaseModel):
    """Who acted, and why, when declining."""

    actor: str = Field(default="buyer", max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class ApprovalResponse(BaseModel):
    order: OrderResponse
    audit_id: str | None = None
    approved_by: str | None = None


class PendingApprovalsResponse(BaseModel):
    count: int
    orders: list[OrderResponse]
