from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.db.account_store import get_account_store
from app.main import app
from app.schemas import SearchRequest
from app.services.search_runner import run_search_once
from fastapi.testclient import TestClient


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
                "market_region": "eu",
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
    assert subscription["criteria"]["market_region"] == "eu"

    listed = client.get("/alerts/subscriptions")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["email_configured"] is True
    assert len(payload["subscriptions"]) == 1
    assert payload["subscriptions"][0]["criteria"]["market_region"] == "eu"


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
                "radius_miles": 250,
                "inventory_scope": "all",
                "max_dealerships": 8,
                "max_pages_per_dealer": 3,
                "market_region": "eu",
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
    scrape_runs = store.list_scrape_runs(user_id=user_id, limit=5)
    assert len(scrape_runs) == 1
    assert scrape_runs[0].trigger_source == "alert_schedule"
    assert scrape_runs[0].status == "success"
    assert scrape_runs[0].radius_miles == 30
    assert runs[0]["summary"]["correlation_id"] == scrape_runs[0].correlation_id


@pytest.mark.asyncio
async def test_run_search_once_passes_market_region_to_stream_search() -> None:
    captured: dict[str, object] = {}

    async def _fake_stream_search(**kwargs):
        captured.update(kwargs)
        yield 'event: done\ndata: {"ok": true}\n\n'

    request = SearchRequest(location="Paris, France", make="BMW", model="X5", market_region="eu")
    with patch("app.services.search_runner.stream_search", new=_fake_stream_search):
        await run_search_once(request)

    assert captured["market_region"] == "eu"
