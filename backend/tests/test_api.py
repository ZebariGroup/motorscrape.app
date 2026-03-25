"""HTTP contract tests for the FastAPI app."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_root() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_server_prefix() -> None:
    r = client.get("/server/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_search_stream_requires_location() -> None:
    r = client.get("/search/stream")
    assert r.status_code == 422


def test_search_stream_no_dealers_mocked() -> None:
    """SSE returns done without calling Google when Places yields no rows."""
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with client.stream("GET", "/search/stream", params={"location": "XX"}) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes())
    assert b"event: done" in body
    assert b"No dealerships" in body
