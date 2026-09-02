"""ORM models.

Money is stored exclusively in **minor units** (paise for INR) as integers.
Floats are never used for money anywhere in this codebase, and Razorpay's Orders
API expects minor units too, so this representation passes straight through
without conversion.
"""

from __future__ import annotations

from typing import Any

from enum import StrEnum

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, as_utc, utcnow

# Portable JSON: JSONB on Postgres (indexable, binary), plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")

__all__ = [
    "Base",
    "TimestampMixin",
    "utcnow",
    "Product",
    "Order",
    "OrderStatus",
    "Conversation",
    "AuditLog",
    "AuditAction",
    "AuditDecision",
    "AuditOutcome",
    "AgentGrant",
    "GrantStatus",
]


class Product(Base, TimestampMixin):
    """A merchant catalog item, exposed to AI agents as a machine-readable record.

    The primary key is a human- and agent-legible slug (``prd-anc-headphones``)
    rather than an opaque integer. Agents quote product ids in conversation and
    those same ids land in the audit trail, so a readable id makes every
    downstream artifact easier to inspect.
    """

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Minor units. 249900 == INR 2,499.00
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Free-form structured attributes (brand, colour, warranty...). Named
    # `attributes` rather than `metadata` because SQLAlchemy reserves
    # `Base.metadata` on every declarative class.
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
        Index("ix_products_active_category", "is_active", "category"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Product {self.id} {self.name!r} {self.price_minor}{self.currency}>"

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


class OrderStatus(StrEnum):
    """Lifecycle of an agent-initiated order.

    The terminal states are PAID, FAILED, and CANCELLED. BLOCKED is reserved for
    Milestone 4: an order the guardrails refused before it ever reached Razorpay,
    which must still be recorded so the refusal is auditable.
    """

    PENDING_APPROVAL = "pending_approval"
    CREATED = "created"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Order(Base, TimestampMixin):
    """An order the purchasing agent created on the buyer's behalf.

    `amount_minor` is denormalised from `unit_price_minor * quantity` at creation
    time on purpose: it is the amount actually sent to Razorpay, and it must stay
    pinned to what was charged even if the product's catalog price changes later.
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Razorpay identifiers. Null until the provider call succeeds, which is what
    # distinguishes "we intended to charge" from "the provider accepted it".
    razorpay_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    razorpay_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)

    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=32),
        nullable=False,
        default=OrderStatus.CREATED,
        index=True,
    )

    conversation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="purchasing-agent")

    # The authority this order was placed under. Nullable because an order the
    # guardrails refused may never have had one — and that refusal is exactly
    # what needs recording.
    grant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    receipt: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )

    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    notes: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint("amount_minor > 0", name="ck_orders_amount_positive"),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Order {self.id} {self.status} {self.amount_minor}{self.currency}>"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            OrderStatus.PAID,
            OrderStatus.FAILED,
            OrderStatus.CANCELLED,
            OrderStatus.BLOCKED,
        }


class Conversation(Base, TimestampMixin):
    """A chat thread between a buyer and the purchasing agent.

    The transcript is stored as a JSON blob in Anthropic message format rather
    than as normalised rows. Turns are only ever appended and always replayed
    whole, so a relational split would add joins without buying anything — and
    the blob round-trips to the API without translation.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    last_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Conversation {self.id} turns={len(self.messages or [])}>"


class AuditAction(StrEnum):
    """The money action an audit entry describes.

    Granting and revoking authority are recorded with the same rigour as a
    purchase: they are the decisions that make every later purchase possible,
    and an audit trail that shows spending but not who authorised it explains
    nothing.
    """

    CREATE_ORDER = "create_order"
    VERIFY_PAYMENT = "verify_payment"
    GRANT_ACCESS = "grant_access"
    REVOKE_ACCESS = "revoke_access"


class AuditDecision(StrEnum):
    """What the guardrails decided, before the action ran."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class AuditOutcome(StrEnum):
    """What actually happened after the decision.

    `PENDING` means the row was written but the action has not finished — the
    state every entry starts in, because the record is created *before* the
    money moves. An entry stuck in PENDING is itself a finding: it means the
    process died mid-action.
    """

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    DECLINED = "declined"
    EXPIRED = "expired"


class AuditLog(Base, TimestampMixin):
    """An immutable-by-convention record of one attempted money action.

    Written **before** the action executes and updated after, so a crash mid-flight
    still leaves evidence that the agent was about to spend. Rows are never
    deleted; a superseded decision is updated in place with its outcome, and the
    `checks` column keeps the exact bounds that were evaluated at the time — not
    the bounds as configured today.
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=32), nullable=False, index=True
    )
    decision: Mapped[AuditDecision] = mapped_column(
        SAEnum(AuditDecision, native_enum=False, length=32), nullable=False, index=True
    )
    outcome: Mapped[AuditOutcome] = mapped_column(
        SAEnum(AuditOutcome, native_enum=False, length=32),
        nullable=False,
        default=AuditOutcome.PENDING,
        index=True,
    )

    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Every bound evaluated, with the limit and the observed value at the time.
    # Snapshotted rather than recomputed so the record stays truthful after the
    # configured caps change.
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Human approval, when the amount crossed the auto-approve threshold.
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    __table_args__ = (
        Index("ix_audit_created_desc", "created_at"),
        Index("ix_audit_decision_outcome", "decision", "outcome"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (
            f"<AuditLog {self.id} {self.action}/{self.decision}"
            f"/{self.outcome} {self.amount_minor}{self.currency}>"
        )


class GrantStatus(StrEnum):
    """Lifecycle of an agent's purchasing authority."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AgentGrant(Base, TimestampMixin):
    """Explicit, revocable authority for an agent to spend on a buyer's behalf.

    This is the consent lifecycle: a buyer grants a capped, expiring allowance
    once, the agent transacts freely inside it without re-approving every
    purchase, and the buyer can revoke it instantly. It sits *above* the
    per-transaction and daily caps — those bound how much can move at a time;
    this bounds whether the agent may act at all.

    Spend against a grant is **computed from the orders that reference it**
    rather than kept as a running counter. A counter can drift from reality
    after a failure; a sum cannot.
    """

    __tablename__ = "agent_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    buyer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="autobuy")
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="purchasing-agent")

    spend_cap_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[GrantStatus] = mapped_column(
        SAEnum(GrantStatus, native_enum=False, length=32),
        nullable=False,
        default=GrantStatus.ACTIVE,
        index=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("spend_cap_minor > 0", name="ck_grants_cap_positive"),
        Index("ix_grants_buyer_status", "buyer_id", "status"),
    )

    def is_live(self, now: datetime | None = None) -> bool:
        """True only if the grant is active AND has not expired."""
        moment = now or utcnow()
        # SQLite hands back naive datetimes; compare like with like.
        expires = as_utc(self.expires_at)
        return self.status is GrantStatus.ACTIVE and expires is not None and expires > moment

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<AgentGrant {self.id} {self.status} cap={self.spend_cap_minor}>"
