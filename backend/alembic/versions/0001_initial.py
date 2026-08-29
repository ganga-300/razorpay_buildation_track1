"""initial empty baseline

Establishes the migration chain. Domain tables (products, orders, audit_logs)
are added in later milestones so each migration maps to one feature.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline revision — intentionally empty."""


def downgrade() -> None:
    """Baseline revision — intentionally empty."""
