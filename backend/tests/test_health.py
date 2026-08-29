"""Health endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import __version__

pytestmark = pytest.mark.asyncio


async def test_liveness_probe(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


async def test_health_reports_ok_and_version(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "AutoBuy"
    assert body["version"] == __version__
    assert body["environment"] == "local"


async def test_health_enumerates_every_dependency(client: AsyncClient) -> None:
    """The health report must name all four dependencies the app relies on."""
    resp = await client.get("/health")
    names = {dep["name"] for dep in resp.json()["dependencies"]}
    assert names == {"database", "redis", "razorpay", "anthropic"}


async def test_health_database_is_reachable(client: AsyncClient) -> None:
    deps = {d["name"]: d for d in (await client.get("/health")).json()["dependencies"]}
    assert deps["database"]["reachable"] is True
