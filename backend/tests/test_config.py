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
    # sslmode is translated to asyncpg's spelling; the credentials are untouched.
    assert s.database_url == "postgresql+asyncpg://user:p%40ss@host:5432/db?ssl=require"
    assert s.is_sqlite is False


# --------------------------------------------------------------------------
# Serverless Postgres (Neon, Supabase): libpq-only query parameters
# --------------------------------------------------------------------------


def test_sslmode_is_translated_for_asyncpg() -> None:
    """asyncpg has never accepted libpq's `sslmode`.

    Neon appends it to every connection string, and leaving it in place fails
    at connect time with `TypeError: connect() got an unexpected keyword
    argument 'sslmode'` — only on deploy, never locally.
    """
    s = Settings(
        database_url=(
            "postgresql://u:p@ep-x.ap-southeast-1.aws.neon.tech/autobuy"
            "?sslmode=require"
        )
    )
    assert "sslmode=" not in s.database_url
    assert "ssl=require" in s.database_url


def test_channel_binding_is_dropped() -> None:
    """Another libpq-only parameter Neon adds; asyncpg negotiates it itself."""
    s = Settings(
        database_url=(
            "postgresql://u:p@ep-x.aws.neon.tech/autobuy"
            "?sslmode=require&channel_binding=require"
        )
    )
    assert "channel_binding" not in s.database_url
    assert "ssl=require" in s.database_url


def test_a_url_with_no_query_string_is_left_clean() -> None:
    """Render's internal URL has no parameters; none should be invented."""
    s = Settings(database_url="postgresql://u:p@dpg-abc-a/autobuy")
    assert s.database_url == "postgresql+asyncpg://u:p@dpg-abc-a/autobuy"
    assert "?" not in s.database_url


def test_an_explicit_ssl_param_is_preserved() -> None:
    s = Settings(database_url="postgresql://u:p@host/db?ssl=verify-full")
    assert "ssl=verify-full" in s.database_url


# --------------------------------------------------------------------------
# Engine tuning for pooled endpoints
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expect_cache_disabled"),
    [
        ("postgresql://u:p@ep-x-pooler.aws.neon.tech/db?sslmode=require", True),
        ("postgresql://u:p@ep-x.aws.neon.tech/db?sslmode=require", False),
        ("postgresql://autobuy:autobuy@localhost:5432/autobuy", False),
    ],
)
def test_pooled_endpoints_disable_the_prepared_statement_cache(
    url: str, expect_cache_disabled: bool
) -> None:
    """PgBouncer in transaction mode breaks asyncpg's prepared statements.

    Sessions are multiplexed across backends, so a statement prepared on one
    connection is missing on the next — surfacing as an intermittent
    InvalidSQLStatementNameError under load rather than a clean startup failure.

    Asserted on the same predicate `db/session.py` uses, so the two cannot drift
    without this failing.
    """
    from app.config import Settings

    settings = Settings(database_url=url)
    is_pooled = "-pooler." in settings.database_url or settings.pgbouncer_mode
    assert is_pooled is expect_cache_disabled


def test_pgbouncer_mode_forces_the_pooled_settings() -> None:
    """Supabase's pooler does not advertise itself with '-pooler'."""
    s = Settings(
        database_url="postgresql://u:p@aws-0-region.pooler.supabase.com/postgres",
        pgbouncer_mode=True,
    )
    assert s.pgbouncer_mode is True
