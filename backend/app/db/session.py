"""Async SQLAlchemy engine + session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# SQLite needs no pool tuning; Postgres benefits from pre-ping to survive
# Render's connection recycling.
_engine_kwargs: dict[str, object] = {"echo": settings.debug, "future": True}
if not settings.is_sqlite:
    _engine_kwargs |= {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}

engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping_database() -> bool:
    """Cheap connectivity probe used by the health check."""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
