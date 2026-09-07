import httpx
import pytest

from app.core import redis_client
from app.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthz_reports_ok_when_dependencies_are_reachable(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_client, "ping", lambda: True)

    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": True, "redis": True}}


async def test_healthz_reports_degraded_when_redis_is_unreachable(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_client, "ping", lambda: False)

    response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": True, "redis": False}}
