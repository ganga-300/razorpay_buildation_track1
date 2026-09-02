"""Consent lifecycle endpoints: grant purchasing authority, and revoke it.

Revocation is deliberately a plain, unconditional endpoint. There is no
confirmation step, no cooling-off period, and no way for the agent to object:
withdrawing authority must be the easiest thing in the system to do, because an
authority you cannot take back instantly is not a grant.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.grants import (
    GrantListResponse,
    GrantRequest,
    GrantResponse,
    RevokeRequest,
)
from app.services import grants as grant_service
from app.services.grants import GrantError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consent"])


@router.get(
    "/grants",
    response_model=GrantListResponse,
    summary="Every grant, and which one is live",
)
async def list_grants(
    session: AsyncSession = Depends(get_session),
    buyer_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> GrantListResponse:
    rows = await grant_service.list_grants(session, buyer_id=buyer_id, limit=limit)
    serialised = [
        GrantResponse.model_validate(await grant_service.serialise(session, g))
        for g in rows
    ]
    live = next((g for g in serialised if g.is_live), None)
    return GrantListResponse(count=len(serialised), active=live, grants=serialised)


@router.post(
    "/grants",
    response_model=GrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant the agent purchasing authority",
    responses={400: {"description": "Invalid cap or expiry"}},
)
async def create_grant(
    request: GrantRequest,
    session: AsyncSession = Depends(get_session),
) -> GrantResponse:
    """Authorise the agent to spend up to a cap, until an expiry.

    Supersedes any existing live grant: two concurrent allowances would make
    "how much may this agent still spend" ambiguous.
    """
    try:
        grant = await grant_service.grant_access(
            session,
            spend_cap_minor=request.spend_cap_minor,
            expires_in_hours=request.expires_in_hours,
            buyer_id=request.buyer_id,
            note=request.note,
        )
    except GrantError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return GrantResponse.model_validate(await grant_service.serialise(session, grant))


@router.post(
    "/grants/{grant_id}/revoke",
    response_model=GrantResponse,
    summary="Revoke the agent's purchasing authority, effective immediately",
    responses={404: {"description": "No such grant"}},
)
async def revoke_grant(
    grant_id: str,
    request: RevokeRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> GrantResponse:
    """Withdraw authority now.

    Idempotent: revoking an already-revoked grant succeeds rather than erroring,
    because a buyer hitting the button twice in a panic should not see a failure.
    """
    body = request or RevokeRequest()
    try:
        grant = await grant_service.revoke_access(
            session,
            grant_id=grant_id,
            revoked_by=body.actor,
            reason=body.reason or "Revoked by the buyer.",
        )
    except GrantError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return GrantResponse.model_validate(await grant_service.serialise(session, grant))
