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


def test_search_stream_accepts_vehicle_category() -> None:
    with patch(
        "app.services.orchestrator.find_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ) as mocked_find:
        with client.stream(
            "GET",
            "/search/stream",
            params={"location": "XX", "vehicle_category": "boat"},
        ) as r:
            assert r.status_code == 200
            _ = b"".join(r.iter_bytes())
    assert mocked_find.await_args.kwargs["vehicle_category"] == "boat"


def test_search_logs_endpoint_returns_run_and_events() -> None:
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with client.stream("GET", "/search/stream", params={"location": "Detroit, MI"}) as r:
            assert r.status_code == 200
            _ = b"".join(r.iter_bytes())

    runs_response = client.get("/search/logs")
    assert runs_response.status_code == 200
    runs = runs_response.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["trigger_source"] == "interactive"
    assert runs[0]["status"] == "success"

    detail_response = client.get(f"/search/logs/{runs[0]['correlation_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run"]["correlation_id"] == runs[0]["correlation_id"]
    assert any(event["event_type"] == "search_started" for event in detail["events"])
    assert any(event["event_type"] == "search_finished" for event in detail["events"])
