"""Account, quota, and session tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.main import app
from fastapi.testclient import TestClient


def test_access_summary_anonymous() -> None:
    client = TestClient(app)
    r = client.get("/auth/access-summary")
    assert r.status_code == 200
    data = r.json()
    assert data["authenticated"] is False
    assert data["tier"] == "anonymous"
    assert data["anonymous"]["searches_remaining"] == 4


def test_signup_login_me_logout() -> None:
    client = TestClient(app)
    r = client.post("/auth/signup", json={"email": "User@Example.com", "password": "hunter22!!"})
    assert r.status_code == 201
    assert client.cookies.get("ms_session")

    r2 = client.get("/auth/me")
    assert r2.status_code == 200
    assert r2.json()["email"] == "user@example.com"
    assert r2.json()["tier"] == "free"

    client.post("/auth/logout")
    r3 = client.get("/auth/me")
    assert r3.status_code == 401


def test_anonymous_quota_sse() -> None:
    """Fifth completed search hits quota message in the stream."""
    client = TestClient(app)
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        for i in range(4):
            with client.stream("GET", "/search/stream", params={"location": f"XX{i}"}) as resp:
                assert resp.status_code == 200
                body = b"".join(resp.iter_bytes())
            assert b"event: done" in body

        with client.stream("GET", "/search/stream", params={"location": "ZZ"}) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes())
    assert b"quota" in body
    assert b"account" in body
