"""Consent lifecycle: grant purchasing authority, spend inside it, revoke it.

The caps bound how much can move. This bounds whether the agent may act at all —
and the property that matters most is that withdrawing authority takes effect
*immediately*, with no window in which a revoked agent can still spend.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utcnow
from app.db.models import (
    AgentGrant,
    AuditAction,
    AuditLog,
    GrantStatus,
    Order,
    OrderStatus,
)
from app.services import grants as grant_service
from app.services.grants import GrantError
from app.services.orders import OrderError, approve_order, create_order
from tests.fakes import FakeRazorpay

pytestmark = pytest.mark.asyncio


async def consent_entries(session: AsyncSession) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.action.in_((AuditAction.GRANT_ACCESS, AuditAction.REVOKE_ACCESS)))
        .order_by(AuditLog.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def revoke_seeded_grant(session: AsyncSession, **kwargs) -> None:
    """Withdraw the grant the fixture seeds, leaving the agent unauthorised."""
    live = await grant_service.active_grant(session)
    assert live is not None
    await grant_service.revoke_access(session, grant_id=live.id, **kwargs)


# --------------------------------------------------------------------------
# Granting
# --------------------------------------------------------------------------


async def test_a_grant_authorises_spending(db_session: AsyncSession) -> None:
    live = await grant_service.active_grant(db_session)
    assert live is not None
    assert live.is_live() is True
    assert live.status is GrantStatus.ACTIVE


async def test_granting_supersedes_the_previous_grant(db_session: AsyncSession) -> None:
    """Two live allowances would make 'how much may it spend' ambiguous."""
    first = await grant_service.active_grant(db_session)
    assert first is not None

    second = await grant_service.grant_access(db_session, spend_cap_minor=100_000)

    await db_session.refresh(first)
    assert first.status is GrantStatus.REVOKED
    assert first.revoke_reason == "Superseded by a new grant."
    assert (await grant_service.active_grant(db_session)).id == second.id


@pytest.mark.parametrize(("cap", "hours"), [(0, 24), (-1, 24), (100, 0), (100, -5)])
async def test_nonsense_grants_are_refused(
    db_session: AsyncSession, cap: int, hours: int
) -> None:
    with pytest.raises(GrantError):
        await grant_service.grant_access(
            db_session, spend_cap_minor=cap, expires_in_hours=hours
        )


# --------------------------------------------------------------------------
# Spending inside a grant
# --------------------------------------------------------------------------


async def test_spend_accumulates_against_the_grant(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    grant = await grant_service.active_grant(db_session)
    assert grant is not None

    await create_order(db_session, product_id="prd-cable", quantity=1)
    info = await grant_service.serialise(db_session, grant)

    assert info["spent"]["amount_minor"] == 34_900
    assert info["remaining"]["amount_minor"] == grant.spend_cap_minor - 34_900


async def test_an_order_records_the_authority_it_used(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    grant = await grant_service.active_grant(db_session)
    created = await create_order(db_session, product_id="prd-cable", quantity=1)

    order = await db_session.get(Order, created["order_id"])
    assert order is not None
    assert order.grant_id == grant.id


async def test_a_refused_order_does_not_consume_the_allowance(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """Blocked spend never happened, so it must not eat into the grant."""
    grant = await grant_service.active_grant(db_session)
    with pytest.raises(OrderError):
        await create_order(db_session, product_id="prd-headphones", quantity=1)

    info = await grant_service.serialise(db_session, grant)
    assert info["spent"]["amount_minor"] == 0


async def test_spending_past_the_grant_cap_is_refused(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    await grant_service.grant_access(db_session, spend_cap_minor=40_000)  # ₹400

    first = await create_order(db_session, product_id="prd-cable")  # ₹349 — fits
    assert first["status"] == OrderStatus.AWAITING_PAYMENT.value

    with pytest.raises(OrderError) as exc:  # ₹349 again — only ₹51 left
        await create_order(db_session, product_id="prd-cable")
    assert exc.value.code == "spend_blocked"
    assert "left on the buyer's grant" in exc.value.message


# --------------------------------------------------------------------------
# Revocation — the property that makes the rest trustworthy
# --------------------------------------------------------------------------


async def test_revocation_blocks_the_very_next_order(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """The roadmap's exact test: revoke, then immediately try to spend."""
    await create_order(db_session, product_id="prd-cable")
    assert len(fake_razorpay.created) == 1

    await revoke_seeded_grant(db_session)

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-cable")

    assert exc.value.code == "spend_blocked"
    assert "no active purchasing authority" in exc.value.message
    # Not merely refused at the end — Razorpay was never contacted again.
    assert len(fake_razorpay.created) == 1


async def test_revocation_names_the_bound_that_failed(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    await revoke_seeded_grant(db_session)

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-cable")

    checks = exc.value.details["guardrail"]["checks"]
    authority = next(c for c in checks if c["name"] == "agent_authority")
    assert authority["passed"] is False
    assert authority["limit_minor"] == 0  # allowance is zero the moment it is revoked


async def test_revoking_is_idempotent(db_session: AsyncSession) -> None:
    """A buyer hitting the button twice in a panic must not see an error."""
    live = await grant_service.active_grant(db_session)
    await grant_service.revoke_access(db_session, grant_id=live.id)
    again = await grant_service.revoke_access(db_session, grant_id=live.id)
    assert again.status is GrantStatus.REVOKED


async def test_revoking_an_unknown_grant_is_an_error(db_session: AsyncSession) -> None:
    with pytest.raises(GrantError) as exc:
        await grant_service.revoke_access(db_session, grant_id="grant-nope")
    assert exc.value.code == "grant_not_found"


async def test_revoking_while_an_order_awaits_approval_blocks_the_approval(
    db_session: AsyncSession, fake_razorpay: FakeRazorpay
) -> None:
    """An order already in flight must fail cleanly, not silently succeed.

    The buyer held a ₹1,299 order for approval, then thought better of the whole
    arrangement and revoked. Approving afterwards must not go through.
    """
    held = await create_order(db_session, product_id="prd-mouse")
    assert held["status"] == OrderStatus.PENDING_APPROVAL.value

    await revoke_seeded_grant(db_session, reason="Changed my mind entirely.")

    with pytest.raises(OrderError) as exc:
        await approve_order(db_session, order_id=held["order_id"])

    assert exc.value.code == "spend_blocked"
    assert fake_razorpay.created == []  # nothing ever reached Razorpay


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------


async def test_an_expired_grant_stops_working(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    """Expiry bites the moment it passes, not when a sweeper next runs."""
    live = await grant_service.active_grant(db_session)
    live.expires_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-cable")
    assert exc.value.code == "spend_blocked"

    await db_session.refresh(live)
    assert live.status is GrantStatus.EXPIRED  # settled lazily, so the UI reads true


# --------------------------------------------------------------------------
# Consent events are audited like money
# --------------------------------------------------------------------------


async def test_the_grant_is_audited(db_session: AsyncSession) -> None:
    entries = await consent_entries(db_session)
    assert len(entries) == 1
    assert entries[0].action is AuditAction.GRANT_ACCESS
    assert entries[0].amount_minor == 10_000_00


async def test_the_revocation_is_audited_with_what_was_withdrawn(
    db_session: AsyncSession, generous_limits: None, fake_razorpay: FakeRazorpay
) -> None:
    grant = await grant_service.active_grant(db_session)
    await create_order(db_session, product_id="prd-cable")  # spend ₹349 of ₹10,000

    await grant_service.revoke_access(db_session, grant_id=grant.id, revoked_by="ganga")

    revoke = (await consent_entries(db_session))[-1]
    assert revoke.action is AuditAction.REVOKE_ACCESS
    assert revoke.approved_by == "ganga"
    # The amount recorded is what the agent could still have spent and now cannot.
    assert revoke.amount_minor == 10_000_00 - 34_900
    assert "withdrawn" in revoke.reason


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


async def test_grant_and_revoke_over_the_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await client.post(
        "/grants", json={"spend_cap_minor": 250_000, "expires_in_hours": 6}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["spend_cap"]["display"] == "₹2,500.00"
    assert body["is_live"] is True

    listed = (await client.get("/grants")).json()
    assert listed["active"]["id"] == body["id"]

    revoked = await client.post(
        f"/grants/{body['id']}/revoke", json={"actor": "ganga", "reason": "Done"}
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    assert (await client.get("/grants")).json()["active"] is None


async def test_revoking_over_the_api_stops_the_agent(
    client: AsyncClient, db_session: AsyncSession, generous_limits: None,
    fake_razorpay: FakeRazorpay,
) -> None:
    """End to end: the dashboard button must actually stop purchases."""
    live = (await client.get("/grants")).json()["active"]
    await client.post(f"/grants/{live['id']}/revoke", json={"actor": "ganga"})

    with pytest.raises(OrderError) as exc:
        await create_order(db_session, product_id="prd-cable")
    assert exc.value.code == "spend_blocked"
    assert fake_razorpay.created == []


async def test_an_invalid_cap_is_rejected_by_the_api(client: AsyncClient) -> None:
    resp = await client.post("/grants", json={"spend_cap_minor": 0})
    assert resp.status_code == 422


async def test_revoking_an_unknown_grant_is_404(client: AsyncClient) -> None:
    resp = await client.post("/grants/grant-nope/revoke")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------


async def test_requiring_a_grant_is_the_default() -> None:
    """Authority a buyer never gave is not something to opt out of."""
    from app.config import Settings

    assert Settings.model_fields["require_agent_grant"].default is True


async def test_disabling_the_requirement_still_reports_the_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning it off must not silently omit the bound from the trail."""
    monkeypatch.setattr(settings, "require_agent_grant", False)
    from app.services.guardrails import evaluate

    decision = await evaluate(db_session, amount_minor=34_900)
    authority = next(c for c in decision.checks if c.name == "agent_authority")
    assert authority.passed is True


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


async def test_timestamps_carry_an_explicit_utc_offset(
    db_session: AsyncSession,
) -> None:
    """SQLite drops the timezone; serialising naively misleads the client.

    A browser parses a naive ISO string as *local* time, so a 24-hour grant
    rendered as "18h left" in IST and every audit timestamp appeared shifted by
    the UTC offset. In a trail whose purpose is saying when things happened,
    that is a correctness bug, not a cosmetic one.
    """
    grant = await grant_service.active_grant(db_session)
    info = await grant_service.serialise(db_session, grant)

    for field in ("expires_at", "created_at"):
        value = info[field]
        assert value is not None
        assert value.endswith("+00:00"), f"{field} has no UTC offset: {value}"


async def test_a_24h_grant_reads_as_roughly_24h_away(
    db_session: AsyncSession,
) -> None:
    from datetime import datetime

    grant = await grant_service.grant_access(
        db_session, spend_cap_minor=100_000, expires_in_hours=24
    )
    info = await grant_service.serialise(db_session, grant)

    hours = (datetime.fromisoformat(info["expires_at"]) - utcnow()).total_seconds() / 3600
    assert 23.5 < hours < 24.5, f"expected ~24h, got {hours:.1f}h"
