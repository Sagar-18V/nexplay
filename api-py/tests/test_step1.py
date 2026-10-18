"""Step 1 contract tests: health, request-id propagation, Express-compatible errors."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x?sslmode=require&channel_binding=require")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

import pytest
from fastapi.testclient import TestClient

from app.core.config import to_async_dsn
from app.main import app
from app.routers import health


async def _up():
    return {"status": "up", "latencyMs": 1}


async def _down():
    raise ConnectionError("nope")


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(health, "check_postgres", _up)
    monkeypatch.setattr(health, "check_redis", _up)
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_health_degraded_when_redis_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_postgres", _up)
    monkeypatch.setattr(health, "check_redis", _down)
    r = client.get("/v1/health")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["data"]["checks"]["redis"] == {"status": "down", "error": "ConnectionError"}


def test_request_id_is_propagated_from_gateway(client, monkeypatch):
    monkeypatch.setattr(health, "check_postgres", _up)
    monkeypatch.setattr(health, "check_redis", _up)
    r = client.get("/v1/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_unknown_route_uses_express_error_shape(client):
    r = client.get("/v1/nope", headers={"X-Request-Id": "rid-1"})
    assert r.status_code == 404
    assert r.json() == {"success": False, "message": "Not Found", "requestId": "rid-1"}


def test_neon_dsn_is_translated_for_asyncpg():
    dsn, args = to_async_dsn(
        "postgresql://u:p@host/db?sslmode=require&channel_binding=require"
    )
    assert dsn == "postgresql+asyncpg://u:p@host/db"
    assert args == {"ssl": True}
