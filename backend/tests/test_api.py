"""HTTP contract tests for the FastAPI app."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.config import settings
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


def test_admin_overview_requires_admin() -> None:
    local_client = TestClient(app)
    unauthorized = local_client.get("/admin/overview")
    assert unauthorized.status_code == 401


def test_admin_overview_allows_bootstrapped_admin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_emails", "matthew@zebarigroup.com")
    local_client = TestClient(app)
    signup = local_client.post("/auth/signup", json={"email": "matthew@zebarigroup.com", "password": "hunter22!!"})
    assert signup.status_code == 201

    response = local_client.get("/admin/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "stats" in payload
    assert payload["stats"]["total_users"] >= 1


def test_admin_user_update_appears_in_audit_and_detail(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_emails", "matthew@zebarigroup.com")
    local_client = TestClient(app)
    admin_signup = local_client.post("/auth/signup", json={"email": "matthew@zebarigroup.com", "password": "hunter22!!"})
    assert admin_signup.status_code == 201

    target_signup = local_client.post("/auth/signup", json={"email": "customer@example.com", "password": "hunter22!!"})
    assert target_signup.status_code == 201
    target_user_id = target_signup.json()["id"]

    patch_response = local_client.patch(f"/admin/users/{target_user_id}", json={"tier": "premium", "is_admin": True})
    assert patch_response.status_code == 200
    assert patch_response.json()["user"]["tier"] == "premium"
    assert patch_response.json()["user"]["is_admin"] is True

    detail_response = local_client.get(f"/admin/users/{target_user_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["user"]["email"] == "customer@example.com"
    assert detail["user"]["tier"] == "premium"
    assert any(log["action"] == "user_updated" for log in detail["audit_logs"])

    audit_response = local_client.get("/admin/audit-log")
    assert audit_response.status_code == 200
    assert any(log["target_id"] == target_user_id for log in audit_response.json()["logs"])
