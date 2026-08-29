"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
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

    return app


app = create_app()
