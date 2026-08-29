"""Response schemas for the health endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DependencyStatus(BaseModel):
    """Readiness of a single external dependency."""

    name: str
    configured: bool = Field(description="Credentials/URL present in the environment")
    reachable: bool | None = Field(
        default=None, description="None when connectivity was not probed"
    )
    detail: str | None = None


class HealthResponse(BaseModel):
    """Overall service health."""

    status: Literal["ok", "degraded"]
    app: str
    environment: str
    version: str
    timestamp: datetime
    dependencies: list[DependencyStatus]
