"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator
from typing import TYPE_CHECKING

# Force a disposable in-memory DB and known-safe config BEFORE app import.
# The suite creates and DROPS every table in teardown. Pointed at a real
# database that wipes the schema while leaving alembic_version intact, so the
# next `alembic upgrade head` reports "already at head" against an empty
# database. Refuse rather than destroy: an exported DATABASE_URL from a previous
# shell command is all it takes.
_requested_db = os.environ.get("DATABASE_URL")
if _requested_db and not _requested_db.startswith("sqlite"):
    raise RuntimeError(
        "Refusing to run the test suite against a non-SQLite database.\n"
        f"  DATABASE_URL = {_requested_db.split('@')[-1]}\n"
        "The suite drops every table in teardown, which would wipe that schema "
        "while leaving alembic_version claiming it is migrated.\n"
        "Unset DATABASE_URL, or set TEST_ALLOW_REAL_DB=1 if you truly mean it."
    ) if os.environ.get("TEST_ALLOW_REAL_DB") != "1" else None

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Pinned, not defaulted: a developer running with AGENT_MODE=scripted in their
# local .env must not silently change what the suite exercises.
os.environ["AGENT_MODE"] = "model"
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("DEBUG", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from tests.fakes import FakeRazorpay

from app.db.base import Base
from app.db.models import Product
from app.db.session import SessionLocal, engine
from app.main import create_app
from app.config import settings
from app.services import orders as orders_service
from app.services.idempotency import reset_store

# A deliberately small catalog spanning the guardrail bands, so tests can assert
# on price filtering and stock filtering without depending on the seed script.
TEST_PRODUCTS: list[dict[str, object]] = [
    {
        "id": "prd-cable",
        "name": "Braided USB-C Cable",
        "description": "Two-metre braided charging cable.",
        "category": "accessories",
        "price_minor": 34_900,
        "stock": 100,
        "attributes": {"brand": "Volt"},
    },
    {
        "id": "prd-mouse",
        "name": "Silent Wireless Mouse",
        "description": "Silent wireless mouse with bluetooth multi-device pairing.",
        "category": "peripherals",
        "price_minor": 129_900,
        "stock": 10,
        "attributes": {"brand": "Volt"},
    },
    {
        "id": "prd-headphones",
        "name": "Wireless Noise Cancelling Headphones",
        "description": "Over-ear wireless headphones with active noise cancellation.",
        "category": "audio",
        "price_minor": 249_900,
        "stock": 5,
        "attributes": {"brand": "Sonora", "anc": True},
    },
    {
        "id": "prd-espresso",
        "name": "Espresso Machine",
        "description": "Semi-automatic espresso machine. Out of stock.",
        "category": "home",
        "price_minor": 899_900,
        "stock": 0,
        "attributes": {"brand": "Terra"},
    },
    {
        "id": "prd-retired",
        "name": "Discontinued Lamp",
        "description": "No longer sold.",
        "category": "home",
        "price_minor": 59_900,
        "stock": 3,
        "attributes": {},
        "is_active": False,
    },
]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create the schema, seed it, and yield a session. Dropped afterwards."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        session.add_all([Product(**row) for row in TEST_PRODUCTS])  # type: ignore[arg-type]
        await session.commit()

        # A live grant, so tests written before the consent lifecycle existed
        # still exercise what they were written for. Without one, every order
        # test would fail on `agent_authority` rather than on the rule it is
        # actually asserting. Consent tests revoke or expire this deliberately.
        from app.services.grants import grant_access

        await grant_access(
            session,
            spend_cap_minor=10_000_00,
            expires_in_hours=24,
            note="Seeded by the test fixture.",
        )

    async with SessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client bound to the ASGI app, against the seeded schema."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def fake_razorpay(monkeypatch: pytest.MonkeyPatch) -> "FakeRazorpay":
    """Substitute the Razorpay client everywhere the order service resolves it."""
    from tests.fakes import FakeRazorpay

    fake = FakeRazorpay()
    monkeypatch.setattr(orders_service, "get_razorpay_client", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def bare_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with no schema — for tests that must not depend on seed data."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _isolate_idempotency_store() -> "Generator[None, None, None]":
    """The store is a process-global; a key left over would leak between tests."""
    reset_store()
    yield
    reset_store()


@pytest.fixture(autouse=True)
def _isolate_llm_usage() -> "Generator[None, None, None]":
    """The cost/usage counters are process-globals; the same leak risk applies."""
    from app.services import llm_usage

    llm_usage.reset()
    yield
    llm_usage.reset()


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry backoff from adding real seconds to the suite."""
    monkeypatch.setattr(settings, "provider_retry_base_delay", 0.0)


@pytest.fixture
def generous_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise every cap out of the way.

    For tests about provider mechanics — amounts, retries, idempotency — where
    the gate is not what is under test. Guardrail behaviour has its own tests
    that run against the real configured limits.
    """
    monkeypatch.setattr(settings, "auto_approve_limit_minor", 10_000_00)
    monkeypatch.setattr(settings, "per_transaction_cap_minor", 50_000_00)
    monkeypatch.setattr(settings, "daily_cap_minor", 100_000_00)
