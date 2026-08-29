"""ORM models.

Milestone 0 intentionally ships no domain tables — `Product`, `Order`, and
`AuditLog` arrive in Milestones 1 and 4. The module exists so Alembic's
autogenerate target and the import graph are stable from the start.
"""

from __future__ import annotations

from app.db.base import Base, TimestampMixin, utcnow

__all__ = ["Base", "TimestampMixin", "utcnow"]
