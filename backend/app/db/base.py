"""Declarative base shared by every ORM model.

Kept in its own module so Alembic can import metadata without pulling in the
FastAPI app (which would create a circular import).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now — used as the Python-side default everywhere."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Re-attach UTC to a datetime that lost its timezone in the database.

    SQLite has no timezone type, so a `DateTime(timezone=True)` column hands
    back a naive value on the way out. Serialised naively, the browser reads it
    as *local* time — a 24-hour grant displays as "18h left" in IST, and audit
    timestamps appear shifted by the UTC offset. In a trail whose whole purpose
    is saying exactly when something happened, that is not cosmetic.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def utc_iso(value: datetime | None) -> str | None:
    """ISO-8601 with an explicit UTC offset, safe for any client to parse."""
    aware = as_utc(value)
    return aware.isoformat() if aware else None


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TimestampMixin:
    """Adds created_at / updated_at to any model that inherits it."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
