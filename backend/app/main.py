"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.catalog import router as catalog_router
from app.api.audit import router as audit_router
from app.api.chat import router as chat_router
from app.api.grants import router as grants_router
from app.api.metrics import router as metrics_router
from app.api.orders import router as orders_router
from app.api.health import router as health_router
from app.config import settings
from app.db.session import engine

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown hooks."""
    logger.info(
        "Starting %s v%s (env=%s, db=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        "sqlite" if settings.is_sqlite else "postgres",
    )
    if not settings.razorpay_configured:
        logger.warning("Razorpay test keys not configured — payment routes will be inert.")
    yield
    await engine.dispose()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Application factory — keeps the app importable and testable."""
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=(
            "Agent-readable commerce API. Every money action is explainable, "
            "bounded, gated, and audited. Razorpay TEST MODE only."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health lives at the root (not under the versioned prefix) so platform
    # probes have a stable, unversioned URL.
    app.include_router(health_router)

    # The catalog is the agent-facing surface; it stays at a short, stable path
    # so an external agent can discover it without version negotiation. The
    # document itself carries `schema_version`.
    app.include_router(catalog_router)

    # Conversational checkout. Streams Server-Sent Events.
    app.include_router(chat_router)

    # Orders and deterministic payment verification.
    app.include_router(orders_router)

    # Audit trail and human-approval gate.
    app.include_router(audit_router)

    # Consent lifecycle: grant and revoke purchasing authority.
    app.include_router(grants_router)

    # What the cost-reduction rules in app/agents/llm.py have measurably saved.
    app.include_router(metrics_router)

    return app


app = create_app()
