"""Supabase implementation of AccountStore."""

from __future__ import annotations

import logging
import time
from typing import Any

from supabase import Client, create_client

from app.config import settings
from app.db.account_store import UserRecord

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


_store: SupabaseAccountStore | None = None

def get_supabase_store() -> SupabaseAccountStore:
    global _store
    if _store is None:
        _store = SupabaseAccountStore()
    return _store
