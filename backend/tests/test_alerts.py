from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.db.account_store import get_account_store
from app.main import app
from app.schemas import SearchRequest
from app.services.search_runner import SearchRunResult
from app.services.search_runner import run_search_once
from fastapi.testclient import TestClient


def _signup_and_promote(client: TestClient) -> str:
    response = client.post("/auth/signup", json={"email": "alerts@example.com", "password": "hunter22!!"})
    assert response.status_code == 201
    user_id = response.json()["id"]
    store = get_account_store(settings.accounts_db_path)
    store.set_tier(user_id, "standard")
    return user_id


def _search_result(
    *,
    listings: list[dict[str, object]],
    correlation_id: str = "alert-correlation",
    scrape_run_id: str = "scrape-run-1",
) -> SearchRunResult:
    return SearchRunResult(
        listings=listings,
        status_messages=["done"],
        errors=[],
        outcome={"ok": True, "correlation_id": correlation_id},
        correlation_id=correlation_id,
        scrape_run_id=scrape_run_id,
    )


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
            "only_send_on_changes": True,
            "include_new_listings": True,
            "include_price_drops": True,
            "min_price_drop_usd": 500,
        },
    )
    assert response.status_code == 201
    subscription = response.json()["subscription"]
    assert subscription["deliver_csv"] is True
    assert subscription["criteria"]["market_region"] == "eu"
    assert subscription["only_send_on_changes"] is True
    assert subscription["include_new_listings"] is True
    assert subscription["include_price_drops"] is True
    assert subscription["min_price_drop_usd"] == 500

    updated = client.patch(
        f"/alerts/subscriptions/{subscription['id']}",
        json={"min_price_drop_usd": None, "include_price_drops": False},
    )
    assert updated.status_code == 200
    updated_subscription = updated.json()["subscription"]
    assert updated_subscription["include_price_drops"] is False
    assert updated_subscription["min_price_drop_usd"] is None

    listed = client.get("/alerts/subscriptions")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["email_configured"] is True
    assert len(payload["subscriptions"]) == 1
    assert payload["subscriptions"][0]["criteria"]["market_region"] == "eu"
    assert payload["subscriptions"][0]["min_price_drop_usd"] is None
    assert payload["subscriptions"][0]["include_price_drops"] is False


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
    assert runs[0]["summary"]["delta"]["total_change_count"] == 0
    scrape_runs = store.list_scrape_runs(user_id=user_id, limit=5)
    assert len(scrape_runs) == 1
    assert scrape_runs[0].trigger_source == "alert_schedule"
    assert scrape_runs[0].status == "success"
    assert scrape_runs[0].radius_miles == 30
    assert runs[0]["summary"]["correlation_id"] == scrape_runs[0].correlation_id


def test_claim_due_alert_subscriptions_prevents_double_claim(monkeypatch) -> None:
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
        },
    )
    subscription_id = create.json()["subscription"]["id"]
    store = get_account_store(settings.accounts_db_path)
    store.update_alert_subscription(user_id, subscription_id, next_run_at=0.0)

    first = store.claim_due_alert_subscriptions(now_ts=1.0, limit=25, claim_ttl_seconds=600)
    second = store.claim_due_alert_subscriptions(now_ts=1.0, limit=25, claim_ttl_seconds=600)

    assert len(first) == 1
    assert len(second) == 0


def test_manual_alert_run_skips_email_when_no_changes(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.resend_api_key", "re_test")
    monkeypatch.setattr("app.config.settings.alerts_from_email", "alerts@example.com")
    client = TestClient(app)
    _signup_and_promote(client)

    create = client.post(
        "/alerts/subscriptions",
        json={
            "name": "Seattle Toyota change-only",
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
            "only_send_on_changes": True,
            "include_new_listings": True,
            "include_price_drops": True,
        },
    )
    subscription_id = create.json()["subscription"]["id"]

    initial_listing = {
        "dealership_website": "https://dealer.example.com",
        "listing_url": "https://dealer.example.com/listings/1",
        "raw_title": "2023 Toyota Tacoma SR5",
        "dealership": "Example Toyota",
        "price": 32000,
    }
    unchanged_listing = {
        **initial_listing,
        "history_seen_count": 2,
        "history_price_change": 0,
    }

    send_email = AsyncMock(return_value={"id": "msg_123"})
    run_once = AsyncMock(
        side_effect=[
            _search_result(listings=[initial_listing], correlation_id="alert-1", scrape_run_id="scrape-1"),
            _search_result(listings=[unchanged_listing], correlation_id="alert-2", scrape_run_id="scrape-2"),
        ]
    )
    with (
        patch("app.services.alerts.run_search_once", run_once),
        patch("app.services.alerts.send_email", send_email),
    ):
        first = client.post(f"/alerts/subscriptions/{subscription_id}/run")
        second = client.post(f"/alerts/subscriptions/{subscription_id}/run")

    assert first.status_code == 200
    assert first.json()["run"]["emailed"] is True
    assert first.json()["run"]["summary"]["delta"]["new_listings_count"] == 1

    assert second.status_code == 200
    second_run = second.json()["run"]
    assert second_run["status"] == "skipped_no_changes"
    assert second_run["emailed"] is False
    assert second_run["csv_attached"] is False
    assert second_run["summary"]["delta"]["total_change_count"] == 0
    assert second_run["summary"]["delta"]["email_skipped_no_changes"] is True
    assert send_email.await_count == 1


def test_manual_alert_run_sends_for_thresholded_price_drop(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.resend_api_key", "re_test")
    monkeypatch.setattr("app.config.settings.alerts_from_email", "alerts@example.com")
    client = TestClient(app)
    _signup_and_promote(client)

    create = client.post(
        "/alerts/subscriptions",
        json={
            "name": "Seattle Toyota drops",
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
            "only_send_on_changes": True,
            "include_new_listings": False,
            "include_price_drops": True,
            "min_price_drop_usd": 500,
        },
    )
    subscription_id = create.json()["subscription"]["id"]

    price_drop_listing = {
        "dealership_website": "https://dealer.example.com",
        "listing_url": "https://dealer.example.com/listings/2",
        "raw_title": "2024 Toyota Tacoma TRD Off-Road",
        "dealership": "Example Toyota",
        "price": 38900,
        "history_seen_count": 3,
        "history_price_change": -600,
    }

    with (
        patch(
            "app.services.alerts.run_search_once",
            AsyncMock(return_value=_search_result(listings=[price_drop_listing], correlation_id="alert-3", scrape_run_id="scrape-3")),
        ),
        patch("app.services.alerts.send_email", AsyncMock(return_value={"id": "msg_456"})) as send_email,
    ):
        response = client.post(f"/alerts/subscriptions/{subscription_id}/run")

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "success"
    assert run["emailed"] is True
    assert run["summary"]["delta"]["price_drop_count"] == 1
    assert run["summary"]["delta"]["largest_price_drop"] == 600
    assert send_email.await_count == 1


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
