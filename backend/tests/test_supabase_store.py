from __future__ import annotations

from types import SimpleNamespace

from app.db.supabase_store import (
    SupabaseAccountStore,
    _missing_alert_change_columns_error,
    _strip_alert_change_option_fields,
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
