from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.db.supabase_store import (
    SupabaseAccountStore,
    _missing_alert_change_columns_error,
    _missing_scrape_run_legacy_columns_error,
    _missing_scrape_run_legacy_update_columns_error,
    _strip_alert_change_option_fields,
    _strip_scrape_run_legacy_option_fields,
    _strip_scrape_run_legacy_update_fields,
)


class _FakeInsertQuery:
    def __init__(self, payloads: list[dict], fail_on_new_fields: bool) -> None:
        self.payloads = payloads
        self.fail_on_new_fields = fail_on_new_fields
        self._payload: dict | None = None

    def insert(self, payload: dict):
        self._payload = dict(payload)
        return self

    def execute(self):
        assert self._payload is not None
        self.payloads.append(self._payload)
        if self.fail_on_new_fields and "only_send_on_changes" in self._payload:
            raise RuntimeError(
                "Could not find the 'only_send_on_changes' column of 'alert_subscriptions' in the schema cache"
            )
        row = {
            "id": "sub_123",
            "user_id": self._payload["user_id"],
            "name": self._payload["name"],
            "criteria_json": self._payload["criteria_json"],
            "cadence": self._payload["cadence"],
            "day_of_week": self._payload["day_of_week"],
            "hour_local": self._payload["hour_local"],
            "timezone": self._payload["timezone"],
            "deliver_csv": self._payload.get("deliver_csv", False),
            "is_active": self._payload.get("is_active", True),
            "next_run_at": self._payload["next_run_at"],
            "created_at": self._payload["next_run_at"],
            "updated_at": self._payload["next_run_at"],
        }
        return SimpleNamespace(data=[row])


class _FakeClient:
    def __init__(self, payloads: list[dict], fail_on_new_fields: bool) -> None:
        self.query = _FakeInsertQuery(payloads, fail_on_new_fields)

    def table(self, name: str):
        assert name == "alert_subscriptions"
        return self.query


class _ExplodingClient:
    def table(self, name: str):
        raise AssertionError(f"unexpected query to {name}")


class _FakeScrapeRunInsertQuery:
    def __init__(self, payloads: list[dict], fail_on_legacy_fields: bool) -> None:
        self.payloads = payloads
        self.fail_on_legacy_fields = fail_on_legacy_fields
        self._payload: dict | None = None

    def insert(self, payload: dict):
        self._payload = dict(payload)
        return self

    def execute(self):
        assert self._payload is not None
        self.payloads.append(self._payload)
        if self.fail_on_legacy_fields and "prefer_small_dealers" in self._payload:
            raise RuntimeError(
                "Could not find the 'prefer_small_dealers' column of 'scrape_runs' in the schema cache"
            )
        row = {
            "id": "run_123",
            "correlation_id": self._payload["correlation_id"],
            "user_id": self._payload.get("user_id"),
            "anon_key": self._payload.get("anon_key"),
            "trigger_source": self._payload["trigger_source"],
            "status": self._payload["status"],
            "location": self._payload["location"],
            "make": self._payload["make"],
            "model": self._payload["model"],
            "vehicle_category": self._payload["vehicle_category"],
            "vehicle_condition": self._payload["vehicle_condition"],
            "inventory_scope": self._payload["inventory_scope"],
            "radius_miles": self._payload["radius_miles"],
            "requested_max_dealerships": self._payload["requested_max_dealerships"],
            "requested_max_pages_per_dealer": self._payload["requested_max_pages_per_dealer"],
            "result_count": 0,
            "dealer_discovery_count": None,
            "dealer_deduped_count": None,
            "dealerships_attempted": 0,
            "dealerships_succeeded": 0,
            "dealerships_failed": 0,
            "error_count": 0,
            "warning_count": 0,
            "error_message": None,
            "summary_json": {},
            "economics_json": {},
            "listings_snapshot_json": None,
            "prefer_small_dealers": self._payload.get("prefer_small_dealers", False),
            "started_at": self._payload["started_at"],
            "completed_at": None,
        }
        return SimpleNamespace(data=[row])


class _FakeScrapeRunClient:
    def __init__(self, payloads: list[dict], fail_on_legacy_fields: bool) -> None:
        self.query = _FakeScrapeRunInsertQuery(payloads, fail_on_legacy_fields)

    def table(self, name: str):
        assert name == "scrape_runs"
        return self.query


def test_strip_alert_change_option_fields_removes_new_delivery_keys() -> None:
    payload = {
        "name": "My alert",
        "deliver_csv": True,
        "only_send_on_changes": True,
        "include_new_listings": False,
        "include_price_drops": True,
        "min_price_drop_usd": 500,
    }

    stripped = _strip_alert_change_option_fields(payload)

    assert stripped == {"name": "My alert", "deliver_csv": True}


def test_missing_alert_change_columns_error_detects_schema_cache_failures() -> None:
    exc = RuntimeError("Could not find the 'min_price_drop_usd' column of 'alert_subscriptions' in the schema cache")

    assert _missing_alert_change_columns_error(exc) is True
    assert _missing_alert_change_columns_error(RuntimeError("some other database failure")) is False


def test_strip_scrape_run_legacy_option_fields_removes_prefer_small_dealers() -> None:
    payload = {
        "correlation_id": "srch-123",
        "inventory_scope": "all",
        "prefer_small_dealers": True,
    }

    stripped = _strip_scrape_run_legacy_option_fields(payload)

    assert stripped == {"correlation_id": "srch-123", "inventory_scope": "all"}


def test_missing_scrape_run_legacy_columns_error_detects_schema_cache_failures() -> None:
    exc = RuntimeError("Could not find the 'prefer_small_dealers' column of 'scrape_runs' in the schema cache")

    assert _missing_scrape_run_legacy_columns_error(exc) is True
    assert _missing_scrape_run_legacy_columns_error(RuntimeError("some other database failure")) is False


def test_strip_scrape_run_legacy_update_fields_removes_listings_snapshot() -> None:
    payload = {
        "status": "success",
        "listings_snapshot_json": [{"vin": "123"}],
        "completed_at": "2026-04-09T00:00:00Z",
    }

    stripped = _strip_scrape_run_legacy_update_fields(payload)

    assert stripped == {"status": "success", "completed_at": "2026-04-09T00:00:00Z"}


def test_missing_scrape_run_legacy_update_columns_error_detects_schema_cache_failures() -> None:
    exc = RuntimeError("Could not find the 'listings_snapshot_json' column of 'scrape_runs' in the schema cache")

    assert _missing_scrape_run_legacy_update_columns_error(exc) is True
    assert _missing_scrape_run_legacy_update_columns_error(RuntimeError("some other database failure")) is False


def test_create_alert_subscription_retries_without_new_fields_on_legacy_schema() -> None:
    payloads: list[dict] = []
    store = object.__new__(SupabaseAccountStore)
    store.client = _FakeClient(payloads, fail_on_new_fields=True)

    subscription = store.create_alert_subscription(
        "user_123",
        name="Legacy-safe alert",
        criteria={"location": "Seattle, WA"},
        cadence="daily",
        day_of_week=None,
        hour_local=8,
        timezone="UTC",
        deliver_csv=True,
        only_send_on_changes=True,
        include_new_listings=False,
        include_price_drops=True,
        min_price_drop_usd=500,
        next_run_at=1.0,
    )

    assert len(payloads) == 2
    assert "only_send_on_changes" in payloads[0]
    assert "only_send_on_changes" not in payloads[1]
    assert subscription.only_send_on_changes is False
    assert subscription.include_new_listings is True
    assert subscription.include_price_drops is True
    assert subscription.min_price_drop_usd is None


def test_create_scrape_run_retries_without_legacy_fields_on_legacy_schema() -> None:
    payloads: list[dict] = []
    store = object.__new__(SupabaseAccountStore)
    store.client = _FakeScrapeRunClient(payloads, fail_on_legacy_fields=True)

    run = store.create_scrape_run(
        correlation_id="srch-legacy-safe",
        user_id=None,
        anon_key="anon-key",
        trigger_source="interactive",
        status="running",
        location="48220",
        make="Smart",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        radius_miles=100,
        requested_max_dealerships=8,
        requested_max_pages_per_dealer=10,
        started_at=1.0,
        prefer_small_dealers=True,
    )

    assert len(payloads) == 2
    assert "prefer_small_dealers" in payloads[0]
    assert "prefer_small_dealers" not in payloads[1]
    assert run.prefer_small_dealers is False


def test_finalize_scrape_run_retries_without_legacy_update_fields_on_legacy_schema() -> None:
    store = object.__new__(SupabaseAccountStore)
    query = MagicMock()
    query.update.return_value = query
    query.eq.return_value = query
    query.select.return_value = query
    query.limit.return_value = query

    final_row = {
        "id": "run_123",
        "correlation_id": "srch-legacy-safe",
        "user_id": None,
        "anon_key": "anon-key",
        "trigger_source": "interactive",
        "status": "failed",
        "location": "48220",
        "make": "Smart",
        "model": "",
        "vehicle_category": "car",
        "vehicle_condition": "all",
        "inventory_scope": "all",
        "prefer_small_dealers": False,
        "radius_miles": 100,
        "requested_max_dealerships": 8,
        "requested_max_pages_per_dealer": 10,
        "result_count": 0,
        "dealer_discovery_count": None,
        "dealer_deduped_count": None,
        "dealerships_attempted": 0,
        "dealerships_succeeded": 0,
        "dealerships_failed": 0,
        "error_count": 0,
        "warning_count": 0,
        "error_message": "failed",
        "summary_json": {"ok": False},
        "economics_json": {},
        "started_at": "2026-04-09T00:00:00Z",
        "completed_at": "2026-04-09T00:01:00Z",
    }
    query.execute.side_effect = [
        RuntimeError("Could not find the 'listings_snapshot_json' column of 'scrape_runs' in the schema cache"),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[final_row]),
    ]

    client = MagicMock()
    client.table.return_value = query
    store.client = client

    run = store.finalize_scrape_run(
        "run_123",
        status="failed",
        result_count=0,
        dealer_discovery_count=None,
        dealer_deduped_count=None,
        dealerships_attempted=0,
        dealerships_succeeded=0,
        dealerships_failed=0,
        error_count=0,
        warning_count=0,
        error_message="failed",
        summary={"ok": False},
        economics={},
        completed_at=1.0,
        listings_snapshot=[{"vin": "123"}],
    )

    assert query.update.call_count == 2
    first_update_payload = query.update.call_args_list[0].args[0]
    second_update_payload = query.update.call_args_list[1].args[0]
    assert "listings_snapshot_json" in first_update_payload
    assert "listings_snapshot_json" not in second_update_payload
    assert run.id == "run_123"


def test_get_user_by_id_skips_legacy_non_uuid_session_ids() -> None:
    store = object.__new__(SupabaseAccountStore)
    store.client = _ExplodingClient()

    assert store.get_user_by_id("42") is None
