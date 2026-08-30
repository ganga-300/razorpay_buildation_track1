"""Configuration guard tests.

The single most important invariant of this project: it can never be pointed
at a live Razorpay account.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_live_razorpay_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="TEST-mode key"):
        Settings(razorpay_key_id="rzp_live_abc123")


def test_test_mode_razorpay_key_is_accepted() -> None:
    s = Settings(razorpay_key_id="rzp_test_abc123", razorpay_key_secret="shh")
    assert s.razorpay_configured is True


def test_blank_razorpay_key_is_allowed_but_not_configured() -> None:
    """A blank key must not crash startup — it degrades the health report."""
    s = Settings(razorpay_key_id="")
    assert s.razorpay_configured is False


def test_cors_origins_parse_into_a_list() -> None:
    s = Settings(cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origin_list == ["http://a.com", "http://b.com"]


# --------------------------------------------------------------------------
# Deployment: async driver normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@host:5432/db",
        "postgresql://u:p@host:5432/db",
    ],
)
def test_managed_postgres_urls_get_the_async_driver(given: str) -> None:
    """Render and friends hand out sync URLs; the async engine needs asyncpg.

    Without this the app boots locally on SQLite and dies on first deploy with
    "The asyncio extension requires an async driver to be used."
    """
    assert Settings(database_url=given).database_url.startswith(
        "postgresql+asyncpg://"
    )


def test_an_explicit_async_url_is_left_alone() -> None:
    url = "postgresql+asyncpg://u:p@host/db"
    assert Settings(database_url=url).database_url == url


def test_sqlite_is_left_alone() -> None:
    url = "sqlite+aiosqlite:///./autobuy.db"
    s = Settings(database_url=url)
    assert s.database_url == url
    assert s.is_sqlite is True


def test_credentials_survive_the_rewrite() -> None:
    """A botched rewrite that drops the password fails only at deploy time."""
    s = Settings(database_url="postgres://user:p%40ss@host:5432/db?sslmode=require")
    assert s.database_url == "postgresql+asyncpg://user:p%40ss@host:5432/db?sslmode=require"
    assert s.is_sqlite is False
