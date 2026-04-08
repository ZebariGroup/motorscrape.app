from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import AccessContext, get_access_context
from app.config import settings, vehicle_category_enabled
from app.db.account_store import AlertRunRecord, AlertSubscriptionRecord, get_account_store
from app.services.alert_schedule import next_run_at_utc, normalize_timezone
from app.services.alerts import execute_alert_subscription, user_can_manage_alerts
from app.services.email_delivery import email_delivery_configured
from app.tiers import limits_for_tier

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertCriteriaBody(BaseModel):
    location: str = Field(min_length=2)
    make: str = ""
    model: str = ""
    vehicle_category: Literal["car", "motorcycle", "boat", "other"] = "car"
    vehicle_condition: Literal["all", "new", "used"] = "all"
    radius_miles: int = Field(default=25, ge=5, le=250)
    inventory_scope: Literal["all", "on_lot_only", "exclude_shared", "include_transit"] = "all"
    prefer_small_dealers: bool = False
    max_dealerships: int | None = Field(default=None, ge=1, le=20)
    max_pages_per_dealer: int | None = Field(default=None, ge=1, le=50)
    market_region: Literal["us", "eu"] = "us"


class AlertSubscriptionBody(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    criteria: AlertCriteriaBody
    cadence: Literal["daily", "weekly"] = "daily"
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    hour_local: int = Field(default=8, ge=0, le=23)
    timezone: str = Field(default="UTC", min_length=1, max_length=120)
    deliver_csv: bool = False
    only_send_on_changes: bool = False
    include_new_listings: bool = True
    include_price_drops: bool = True
    min_price_drop_usd: float | None = Field(default=None, ge=0)
    is_active: bool = True

    @field_validator("timezone")
    @classmethod
    def _normalize_timezone(cls, value: str) -> str:
        return normalize_timezone(value)


class AlertSubscriptionUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    criteria: AlertCriteriaBody | None = None
    cadence: Literal["daily", "weekly"] | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    hour_local: int | None = Field(default=None, ge=0, le=23)
    timezone: str | None = Field(default=None, min_length=1, max_length=120)
    deliver_csv: bool | None = None
    only_send_on_changes: bool | None = None
    include_new_listings: bool | None = None
    include_price_drops: bool | None = None
    min_price_drop_usd: float | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _normalize_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_timezone(value)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _require_paid_user(ctx: AccessContext):
    if ctx.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in to manage email alerts.")
    if not user_can_manage_alerts(ctx.tier):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Email alerts are available on Standard, Premium, Enterprise, and Custom plans.",
        )


def _serialize_subscription(record: AlertSubscriptionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "criteria": record.criteria,
        "cadence": record.cadence,
        "day_of_week": record.day_of_week,
        "hour_local": record.hour_local,
        "timezone": record.timezone,
        "deliver_csv": record.deliver_csv,
        "only_send_on_changes": record.only_send_on_changes,
        "include_new_listings": record.include_new_listings,
        "include_price_drops": record.include_price_drops,
        "min_price_drop_usd": record.min_price_drop_usd,
        "is_active": record.is_active,
        "next_run_at": _iso(record.next_run_at),
        "last_run_at": _iso(record.last_run_at),
        "last_run_status": record.last_run_status,
        "last_result_count": record.last_result_count,
        "last_error": record.last_error,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


def _serialize_run(record: AlertRunRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "subscription_id": record.subscription_id,
        "trigger_source": record.trigger_source,
        "status": record.status,
        "result_count": record.result_count,
        "emailed": record.emailed,
        "csv_attached": record.csv_attached,
        "error_message": record.error_message,
        "summary": record.summary,
        "started_at": _iso(record.started_at),
        "completed_at": _iso(record.completed_at),
    }


def _next_run_for_body(body: AlertSubscriptionBody | AlertSubscriptionUpdateBody) -> float:
    return next_run_at_utc(
        cadence=body.cadence or "daily",
        hour_local=body.hour_local if body.hour_local is not None else 8,
        timezone_name=body.timezone or "UTC",
        day_of_week=body.day_of_week,
    ).timestamp()


@router.get("/subscriptions")
def list_alert_subscriptions(ctx: Annotated[AccessContext, Depends(get_access_context)]) -> dict[str, Any]:
    _require_paid_user(ctx)
    store = get_account_store(settings.accounts_db_path)
    subscriptions = store.list_alert_subscriptions(ctx.user_id)
    runs = store.list_alert_runs(ctx.user_id, limit=20)
    return {
        "subscriptions": [_serialize_subscription(record) for record in subscriptions],
        "runs": [_serialize_run(record) for record in runs],
        "email_configured": email_delivery_configured(),
        "limits": {
            "tier": ctx.tier,
            "max_dealerships": limits_for_tier(ctx.tier).max_dealerships,
            "max_radius_miles": limits_for_tier(ctx.tier).max_radius_miles,
        },
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_alert_subscription(
    body: AlertSubscriptionBody,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, Any]:
    _require_paid_user(ctx)
    if not vehicle_category_enabled(body.criteria.vehicle_category):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Vehicle category '{body.criteria.vehicle_category}' is not enabled.",
        )
    store = get_account_store(settings.accounts_db_path)
    subscription = store.create_alert_subscription(
        ctx.user_id,
        name=body.name.strip(),
        criteria=body.criteria.model_dump(mode="json"),
        cadence=body.cadence,
        day_of_week=body.day_of_week,
        hour_local=body.hour_local,
        timezone=body.timezone,
        deliver_csv=body.deliver_csv,
        only_send_on_changes=body.only_send_on_changes,
        include_new_listings=body.include_new_listings,
        include_price_drops=body.include_price_drops,
        min_price_drop_usd=body.min_price_drop_usd,
        next_run_at=_next_run_for_body(body),
    )
    if not body.is_active:
        subscription = store.update_alert_subscription(
            ctx.user_id,
            subscription.id,
            is_active=False,
        ) or subscription
    return {"subscription": _serialize_subscription(subscription)}


@router.patch("/subscriptions/{subscription_id}")
def update_alert_subscription(
    subscription_id: str,
    body: AlertSubscriptionUpdateBody,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, Any]:
    _require_paid_user(ctx)
    if body.criteria is not None and not vehicle_category_enabled(body.criteria.vehicle_category):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Vehicle category '{body.criteria.vehicle_category}' is not enabled.",
        )
    store = get_account_store(settings.accounts_db_path)
    existing = store.get_alert_subscription(ctx.user_id, subscription_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert subscription not found.")
    cadence = body.cadence or existing.cadence
    day_of_week = body.day_of_week if body.cadence == "weekly" or body.day_of_week is not None else existing.day_of_week
    hour_local = body.hour_local if body.hour_local is not None else existing.hour_local
    timezone_name = body.timezone or existing.timezone
    next_run_at = _next_run_for_body(
        AlertSubscriptionBody(
            name=body.name or existing.name,
            criteria=AlertCriteriaBody.model_validate(body.criteria.model_dump(mode="json") if body.criteria else existing.criteria),
            cadence=cadence,
            day_of_week=day_of_week,
            hour_local=hour_local,
            timezone=timezone_name,
            deliver_csv=body.deliver_csv if body.deliver_csv is not None else existing.deliver_csv,
            only_send_on_changes=(
                body.only_send_on_changes
                if body.only_send_on_changes is not None
                else existing.only_send_on_changes
            ),
            include_new_listings=(
                body.include_new_listings
                if body.include_new_listings is not None
                else existing.include_new_listings
            ),
            include_price_drops=(
                body.include_price_drops
                if body.include_price_drops is not None
                else existing.include_price_drops
            ),
            min_price_drop_usd=(
                body.min_price_drop_usd
                if "min_price_drop_usd" in body.model_fields_set
                else existing.min_price_drop_usd
            ),
            is_active=body.is_active if body.is_active is not None else existing.is_active,
        )
    )
    updated = store.update_alert_subscription(
        ctx.user_id,
        subscription_id,
        name=body.name.strip() if body.name is not None else None,
        criteria=body.criteria.model_dump(mode="json") if body.criteria is not None else None,
        cadence=body.cadence,
        day_of_week=day_of_week,
        hour_local=body.hour_local,
        timezone=body.timezone,
        deliver_csv=body.deliver_csv,
        only_send_on_changes=body.only_send_on_changes,
        include_new_listings=body.include_new_listings,
        include_price_drops=body.include_price_drops,
        min_price_drop_usd=body.min_price_drop_usd,
        min_price_drop_usd_provided="min_price_drop_usd" in body.model_fields_set,
        is_active=body.is_active,
        next_run_at=next_run_at,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert subscription not found.")
    return {"subscription": _serialize_subscription(updated)}


@router.delete("/subscriptions/{subscription_id}")
def delete_alert_subscription(
    subscription_id: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, bool]:
    _require_paid_user(ctx)
    store = get_account_store(settings.accounts_db_path)
    deleted = store.delete_alert_subscription(ctx.user_id, subscription_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert subscription not found.")
    return {"ok": True}


@router.post("/subscriptions/{subscription_id}/run")
async def run_alert_subscription_now(
    subscription_id: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, Any]:
    _require_paid_user(ctx)
    store = get_account_store(settings.accounts_db_path)
    subscription = store.get_alert_subscription(ctx.user_id, subscription_id)
    if subscription is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert subscription not found.")
    user = store.get_user_by_id(ctx.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    outcome = await execute_alert_subscription(
        store=store,
        user=user,
        subscription=subscription,
        trigger_source="manual",
    )
    return {"run": _serialize_run(outcome["run"]), "quota_blocked": outcome["quota_blocked"]}


@router.post("/internal/run-due")
async def run_due_alert_subscriptions(
    x_alerts_secret: Annotated[str | None, Header(alias="X-Alerts-Secret")] = None,
) -> dict[str, Any]:
    configured_secret = (settings.alerts_internal_secret or "").strip()
    if not configured_secret or x_alerts_secret != configured_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid alerts secret.")
    store = get_account_store(settings.accounts_db_path)
    due = store.claim_due_alert_subscriptions(
        now_ts=datetime.now(UTC).timestamp(),
        limit=25,
        claim_ttl_seconds=settings.alerts_due_claim_ttl_seconds,
    )
    runs: list[dict[str, Any]] = []
    for subscription in due:
        user = store.get_user_by_id(subscription.user_id)
        if user is None or not user_can_manage_alerts(user.tier):
            continue
        outcome = await execute_alert_subscription(
            store=store,
            user=user,
            subscription=subscription,
            trigger_source="schedule",
        )
        runs.append(_serialize_run(outcome["run"]))
    return {"processed": len(runs), "runs": runs}
