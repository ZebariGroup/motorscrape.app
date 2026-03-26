from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.db.account_store import get_account_store
from app.main import app


def _signup_and_promote(client: TestClient) -> str:
    response = client.post("/auth/signup", json={"email": "alerts@example.com", "password": "hunter22!!"})
    assert response.status_code == 201
    user_id = response.json()["id"]
    store = get_account_store(settings.accounts_db_path)
    store.set_tier(user_id, "standard")
    return user_id


def test_paid_user_can_create_and_list_alerts(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.resend_api_key", "re_test")
    monkeypatch.setattr("app.config.settings.alerts_from_email", "alerts@example.com")
    client = TestClient(app)
    _signup_and_promote(client)

    response = client.post(
        "/alerts/subscriptions",
        json={
            "name": "Seattle Toyota daily",
            "criteria": {
                "location": "Seattle, WA",
                "make": "Toyota",
                "model": "Tacoma",
                "vehicle_condition": "used",
                "radius_miles": 25,
                "inventory_scope": "all",
                "max_dealerships": 8,
                "max_pages_per_dealer": 3,
            },
            "cadence": "daily",
            "hour_local": 8,
            "timezone": "UTC",
            "deliver_csv": True,
        },
    )
    assert response.status_code == 201
    subscription = response.json()["subscription"]
    assert subscription["deliver_csv"] is True

    listed = client.get("/alerts/subscriptions")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["email_configured"] is True
    assert len(payload["subscriptions"]) == 1


def test_internal_due_runner_executes_alert(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.resend_api_key", "re_test")
    monkeypatch.setattr("app.config.settings.alerts_from_email", "alerts@example.com")
    monkeypatch.setattr("app.config.settings.alerts_internal_secret", "secret-123")
    client = TestClient(app)
    user_id = _signup_and_promote(client)
    create = client.post(
        "/alerts/subscriptions",
        json={
            "name": "Seattle Toyota daily",
            "criteria": {
                "location": "Seattle, WA",
                "make": "Toyota",
                "model": "Tacoma",
                "vehicle_condition": "used",
                "radius_miles": 25,
                "inventory_scope": "all",
                "max_dealerships": 8,
                "max_pages_per_dealer": 3,
            },
            "cadence": "daily",
            "hour_local": 8,
            "timezone": "UTC",
            "deliver_csv": True,
        },
    )
    subscription_id = create.json()["subscription"]["id"]
    store = get_account_store(settings.accounts_db_path)
    store.update_alert_subscription(user_id, subscription_id, next_run_at=0.0)

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=[]),
        patch("app.services.alerts.send_email", new_callable=AsyncMock, return_value={"id": "msg_123"}),
    ):
        response = client.post("/alerts/internal/run-due", headers={"X-Alerts-Secret": "secret-123"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1

    listed = client.get("/alerts/subscriptions")
    runs = listed.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["emailed"] is True
