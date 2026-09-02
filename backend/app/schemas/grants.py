"""Consent-lifecycle API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.catalog import Money


class GrantRequest(BaseModel):
    """Authorise the agent to spend, up to a cap, until an expiry."""

    spend_cap_minor: int = Field(
        gt=0,
        le=10_000_000,
        description="Total the agent may spend under this grant, in minor units (paise).",
    )
    expires_in_hours: int = Field(default=24, gt=0, le=8760)
    buyer_id: str = Field(default="buyer", max_length=64)
    note: str | None = Field(default=None, max_length=500)


class RevokeRequest(BaseModel):
    actor: str = Field(default="buyer", max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class GrantResponse(BaseModel):
    """One grant, with live spend against it."""

    id: str
    buyer_id: str
    merchant_id: str
    agent_id: str
    status: str
    is_live: bool
    spend_cap: Money
    spent: Money
    remaining: Money
    used_fraction: float
    expires_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    revoke_reason: str | None = None
    note: str | None = None
    created_at: str | None = None


class GrantListResponse(BaseModel):
    count: int
    active: GrantResponse | None = Field(
        default=None, description="The buyer's live grant, if any"
    )
    grants: list[GrantResponse]
