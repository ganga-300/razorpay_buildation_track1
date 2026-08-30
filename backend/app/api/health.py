"""Health & readiness endpoints.

`/health` is intentionally dependency-aware but never fails hard: a missing
Razorpay key degrades the report rather than 500-ing, so the container stays
schedulable while the operator fixes configuration.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.db.base import utcnow
from app.db.session import ping_database
from app.schemas.health import DependencyStatus, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health() -> HealthResponse:
    """Report service and dependency status."""
    db_reachable = await ping_database()

    dependencies = [
        DependencyStatus(
            name="database",
            configured=True,
            reachable=db_reachable,
            detail="sqlite" if settings.is_sqlite else "postgres",
        ),
        DependencyStatus(
            name="redis",
            configured=settings.redis_url is not None,
            reachable=None,
            detail=None if settings.redis_url else "unset — using in-process fallback",
        ),
        DependencyStatus(
            name="razorpay",
            configured=settings.razorpay_configured,
            reachable=None,
            detail="test mode" if settings.razorpay_configured else "keys not set",
        ),
        DependencyStatus(
            name="anthropic",
            # In scripted mode the agent needs no model, so a missing key is not
            # a gap — reporting it as one would send an operator hunting a
            # problem that does not exist.
            configured=(
                True if settings.agent_mode == "scripted" else settings.anthropic_configured
            ),
            reachable=None,
            detail=(
                "not required — AGENT_MODE=scripted"
                if settings.agent_mode == "scripted"
                else (settings.anthropic_model if settings.anthropic_configured else "key not set")
            ),
        ),
    ]

    status = "ok" if db_reachable else "degraded"

    return HealthResponse(
        status=status,
        app=settings.app_name,
        environment=settings.environment,
        version=__version__,
        timestamp=utcnow(),
        dependencies=dependencies,
    )


@router.get("/health/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Trivial liveness probe for the platform scheduler."""
    return {"status": "alive"}
