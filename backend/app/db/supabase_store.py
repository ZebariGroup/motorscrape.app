"""Supabase implementation of AccountStore."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from app.config import settings
from app.db.account_store import AlertRunRecord, AlertSubscriptionRecord, UserRecord

logger = logging.getLogger(__name__)


class SupabaseAccountStore:
    def __init__(self) -> None:
        url = settings.supabase_url
        key = settings.supabase_service_key
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        self.client: Client = create_client(url, key)

    def create_user(self, email: str, password: str, *, tier: str = "free") -> UserRecord:
        email_n = email.strip().lower()
        res = self.client.auth.admin.create_user({
            "email": email_n,
            "password": password,
            "email_confirm": True
        })
        if not res.user:
            raise RuntimeError("Failed to create user")

        user_id = res.user.id

        # Profile is created via trigger, but we might need to update the tier
        if tier != "free":
            self.client.table("profiles").update({"tier": tier}).eq("id", user_id).execute()

        return self.get_user_by_id(user_id) # type: ignore[return-value]

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        res = self.client.table("profiles").select("*").eq("id", user_id).execute()
        if not res.data:
            return None
        return _row_to_user(res.data[0])

    def get_user_by_email(self, email: str) -> UserRecord | None:
        res = self.client.table("profiles").select("*").eq("email", email.strip().lower()).execute()
        if not res.data:
            return None
        return _row_to_user(res.data[0])

    def verify_login(self, email: str, password: str) -> UserRecord | None:
        try:
            res = self.client.auth.sign_in_with_password({"email": email.strip().lower(), "password": password})
            if res.user:
                return self.get_user_by_id(res.user.id)
        except Exception:
            return None
        return None

    def update_password(self, user_id: str, new_password: str) -> None:
        self.client.auth.admin.update_user_by_id(user_id, {"password": new_password})

    def set_tier(
        self,
        user_id: str,
        tier: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        stripe_metered_item_id: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {"tier": tier}
        if stripe_customer_id is not None:
            updates["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            updates["stripe_subscription_id"] = stripe_subscription_id
        if stripe_metered_item_id is not None:
            updates["stripe_metered_item_id"] = stripe_metered_item_id

        self.client.table("profiles").update(updates).eq("id", user_id).execute()

    def set_metered_item(self, user_id: str, metered_item_id: str | None) -> None:
        self.client.table("profiles").update({"stripe_metered_item_id": metered_item_id}).eq("id", user_id).execute()

    def monthly_usage(self, user_id: str, period: str) -> tuple[int, int]:
        res = self.client.table("usage_monthly").select("search_count, overage_count").eq("user_id", user_id).eq("period", period).execute()
        if not res.data:
            return (0, 0)
        return (int(res.data[0]["search_count"]), int(res.data[0]["overage_count"]))

    def increment_search_completed(
        self,
        user_id: str,
        period: str,
        *,
        counts_as_overage: bool,
    ) -> tuple[int, int]:
        # Using Supabase RPC for atomic increment
        res = self.client.rpc("increment_usage", {
            "p_user_id": user_id,
            "p_period": period,
            "p_is_overage": counts_as_overage
        }).execute()

        if res.data:
            return (int(res.data[0]["search_count"]), int(res.data[0]["overage_count"]))

        # Fallback if RPC is not created yet
        current = self.monthly_usage(user_id, period)
        updates = {
            "user_id": user_id,
            "period": period,
            "search_count": current[0] + (0 if counts_as_overage else 1),
            "overage_count": current[1] + (1 if counts_as_overage else 0)
        }
        res2 = self.client.table("usage_monthly").upsert(updates).execute()
        return (int(res2.data[0]["search_count"]), int(res2.data[0]["overage_count"]))

    def anon_get(self, anon_key: str) -> int:
        res = self.client.table("anon_usage").select("search_count").eq("anon_key", anon_key).execute()
        if not res.data:
            return 0
        return int(res.data[0]["search_count"])

    def anon_increment(self, anon_key: str) -> int:
        res = self.client.rpc("increment_anon_usage", {"p_anon_key": anon_key}).execute()
        if res.data:
            return int(res.data)

        # Fallback
        current = self.anon_get(anon_key)
        new_count = current + 1
        self.client.table("anon_usage").upsert({"anon_key": anon_key, "search_count": new_count}).execute()
        return new_count

    def rate_tick(self, bucket_key: str, *, window_seconds: int = 60, limit: int) -> bool:
        window = int(time.time() // window_seconds)
        res = self.client.rpc("rate_tick", {
            "p_bucket_key": bucket_key,
            "p_window_start": window,
            "p_limit": limit
        }).execute()
        if res.data is not None:
            return bool(res.data)

        # Fallback
        res2 = self.client.table("rate_buckets").select("count").eq("bucket_key", bucket_key).eq("window_start", window).execute()
        current = int(res2.data[0]["count"]) if res2.data else 0
        if current + 1 > limit:
            return False
        self.client.table("rate_buckets").upsert({
            "bucket_key": bucket_key,
            "window_start": window,
            "count": current + 1
        }).execute()
        return True

    def prune_old_rate_buckets(self, *, max_age_windows: int = 5, window_seconds: int = 60) -> None:
        cutoff = int(time.time() // window_seconds) - max_age_windows
        self.client.table("rate_buckets").delete().lt("window_start", cutoff).execute()

    def create_alert_subscription(
        self,
        user_id: str,
        *,
        name: str,
        criteria: dict[str, Any],
        cadence: str,
        day_of_week: int | None,
        hour_local: int,
        timezone: str,
        deliver_csv: bool,
        next_run_at: float,
    ) -> AlertSubscriptionRecord:
        payload = {
            "user_id": user_id,
            "name": name,
            "criteria_json": criteria,
            "cadence": cadence,
            "day_of_week": day_of_week,
            "hour_local": hour_local,
            "timezone": timezone,
            "deliver_csv": deliver_csv,
            "is_active": True,
            "next_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_run_at)),
        }
        res = self.client.table("alert_subscriptions").insert(payload).execute()
        return _row_to_alert_subscription(res.data[0])

    def list_alert_subscriptions(self, user_id: str) -> list[AlertSubscriptionRecord]:
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("is_active", desc=True)
            .order("next_run_at")
            .execute()
        )
        return [_row_to_alert_subscription(row) for row in (res.data or [])]

    def get_alert_subscription(self, user_id: str, subscription_id: str) -> AlertSubscriptionRecord | None:
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", subscription_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_alert_subscription(res.data[0])

    def update_alert_subscription(
        self,
        user_id: str,
        subscription_id: str,
        *,
        name: str | None = None,
        criteria: dict[str, Any] | None = None,
        cadence: str | None = None,
        day_of_week: int | None = None,
        hour_local: int | None = None,
        timezone: str | None = None,
        deliver_csv: bool | None = None,
        is_active: bool | None = None,
        next_run_at: float | None = None,
        last_run_at: float | None = None,
        last_run_status: str | None = None,
        last_result_count: int | None = None,
        last_error: str | None = None,
    ) -> AlertSubscriptionRecord | None:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if criteria is not None:
            updates["criteria_json"] = criteria
        if cadence is not None:
            updates["cadence"] = cadence
            updates["day_of_week"] = day_of_week
        if hour_local is not None:
            updates["hour_local"] = hour_local
        if timezone is not None:
            updates["timezone"] = timezone
        if deliver_csv is not None:
            updates["deliver_csv"] = deliver_csv
        if is_active is not None:
            updates["is_active"] = is_active
        if next_run_at is not None:
            updates["next_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_run_at))
        if last_run_at is not None:
            updates["last_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_run_at))
        if last_run_status is not None:
            updates["last_run_status"] = last_run_status
        if last_result_count is not None:
            updates["last_result_count"] = last_result_count
        if last_error is not None or last_error == "":
            updates["last_error"] = last_error
        if not updates:
            return self.get_alert_subscription(user_id, subscription_id)
        self.client.table("alert_subscriptions").update(updates).eq("user_id", user_id).eq("id", subscription_id).execute()
        return self.get_alert_subscription(user_id, subscription_id)

    def delete_alert_subscription(self, user_id: str, subscription_id: str) -> bool:
        res = self.client.table("alert_subscriptions").delete().eq("user_id", user_id).eq("id", subscription_id).execute()
        return bool(res.data)

    def list_due_alert_subscriptions(self, *, now_ts: float, limit: int = 25) -> list[AlertSubscriptionRecord]:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("is_active", True)
            .lte("next_run_at", now_iso)
            .order("next_run_at")
            .limit(limit)
            .execute()
        )
        return [_row_to_alert_subscription(row) for row in (res.data or [])]

    def create_alert_run(
        self,
        *,
        subscription_id: str,
        user_id: str,
        trigger_source: str,
        status: str,
        result_count: int,
        emailed: bool,
        csv_attached: bool,
        error_message: str | None,
        summary: dict[str, Any],
        started_at: float,
        completed_at: float | None,
    ) -> AlertRunRecord:
        payload = {
            "subscription_id": subscription_id,
            "user_id": user_id,
            "trigger_source": trigger_source,
            "status": status,
            "result_count": result_count,
            "emailed": emailed,
            "csv_attached": csv_attached,
            "error_message": error_message,
            "summary_json": summary,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed_at)) if completed_at is not None else None,
        }
        res = self.client.table("alert_runs").insert(payload).execute()
        return _row_to_alert_run(res.data[0])

    def list_alert_runs(self, user_id: str, *, limit: int = 20) -> list[AlertRunRecord]:
        res = (
            self.client.table("alert_runs")
            .select("*")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [_row_to_alert_run(row) for row in (res.data or [])]


def _row_to_user(row: dict[str, Any]) -> UserRecord:
    ent = row.get("entitlements_json") or {}
    return UserRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        tier=str(row["tier"]),
        stripe_customer_id=row.get("stripe_customer_id"),
        stripe_subscription_id=row.get("stripe_subscription_id"),
        stripe_metered_item_id=row.get("stripe_metered_item_id"),
        entitlements=ent,
    )


def _row_to_alert_subscription(row: dict[str, Any]) -> AlertSubscriptionRecord:
    return AlertSubscriptionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        criteria=dict(row.get("criteria_json") or {}),
        cadence=str(row["cadence"]),
        day_of_week=int(row["day_of_week"]) if row.get("day_of_week") is not None else None,
        hour_local=int(row["hour_local"]),
        timezone=str(row["timezone"]),
        deliver_csv=bool(row.get("deliver_csv")),
        is_active=bool(row.get("is_active")),
        next_run_at=_ts(row.get("next_run_at")),
        last_run_at=_ts(row.get("last_run_at")) if row.get("last_run_at") is not None else None,
        last_run_status=str(row["last_run_status"]) if row.get("last_run_status") is not None else None,
        last_result_count=int(row["last_result_count"]) if row.get("last_result_count") is not None else None,
        last_error=str(row["last_error"]) if row.get("last_error") is not None else None,
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


def _row_to_alert_run(row: dict[str, Any]) -> AlertRunRecord:
    return AlertRunRecord(
        id=str(row["id"]),
        subscription_id=str(row["subscription_id"]),
        user_id=str(row["user_id"]),
        trigger_source=str(row["trigger_source"]),
        status=str(row["status"]),
        result_count=int(row.get("result_count") or 0),
        emailed=bool(row.get("emailed")),
        csv_attached=bool(row.get("csv_attached")),
        error_message=str(row["error_message"]) if row.get("error_message") is not None else None,
        summary=dict(row.get("summary_json") or {}),
        started_at=_ts(row.get("started_at")),
        completed_at=_ts(row.get("completed_at")) if row.get("completed_at") is not None else None,
    )


def _ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()
    raise TypeError(f"Unsupported timestamp value: {value!r}")


_store: SupabaseAccountStore | None = None

def get_supabase_store() -> SupabaseAccountStore:
    global _store
    if _store is None:
        _store = SupabaseAccountStore()
    return _store
