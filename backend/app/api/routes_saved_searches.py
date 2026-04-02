from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AccessContext, get_access_context
from app.config import settings, vehicle_category_enabled
from app.db.account_store import SavedSearchRecord, get_account_store

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])

_PAID_SAVED_SEARCH_TIERS = {"standard", "premium", "max_pro", "enterprise", "custom"}


class SavedSearchCriteriaBody(BaseModel):
    location: str = Field(min_length=2)
    make: str = ""
    model: str = ""
    vehicle_category: Literal["car", "motorcycle", "boat", "other"] = "car"
    vehicle_condition: Literal["all", "new", "used"] = "all"
    radius_miles: int = Field(default=25, ge=5, le=250)
    inventory_scope: Literal["all", "on_lot_only", "exclude_shared", "include_transit"] = "all"
    max_dealerships: int | None = Field(default=None, ge=1, le=20)
    max_pages_per_dealer: int | None = Field(default=None, ge=1, le=50)
    market_region: Literal["us", "eu"] = "us"


class SavedSearchBody(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    criteria: SavedSearchCriteriaBody


class SavedSearchUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    criteria: SavedSearchCriteriaBody | None = None


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _require_saved_search_access(ctx: AccessContext) -> None:
    if ctx.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in to manage saved searches.")
    if (ctx.tier or "").lower() not in _PAID_SAVED_SEARCH_TIERS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Saved searches are available on Standard, Premium, Enterprise, and Custom plans.",
        )


def _validate_criteria(criteria: SavedSearchCriteriaBody) -> None:
    if not vehicle_category_enabled(criteria.vehicle_category):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Vehicle category '{criteria.vehicle_category}' is not enabled.",
        )


def _serialize_saved_search(record: SavedSearchRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "criteria": record.criteria,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


@router.get("")
def list_saved_searches(ctx: Annotated[AccessContext, Depends(get_access_context)]) -> dict[str, Any]:
    _require_saved_search_access(ctx)
    store = get_account_store(settings.accounts_db_path)
    return {"saved_searches": [_serialize_saved_search(row) for row in store.list_saved_searches(ctx.user_id)]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_saved_search(
    body: SavedSearchBody,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, Any]:
    _require_saved_search_access(ctx)
    _validate_criteria(body.criteria)
    store = get_account_store(settings.accounts_db_path)
    saved_search = store.create_saved_search(
        ctx.user_id,
        name=body.name.strip(),
        criteria=body.criteria.model_dump(mode="json"),
    )
    return {"saved_search": _serialize_saved_search(saved_search)}


@router.patch("/{saved_search_id}")
def update_saved_search(
    saved_search_id: str,
    body: SavedSearchUpdateBody,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, Any]:
    _require_saved_search_access(ctx)
    if body.criteria is not None:
        _validate_criteria(body.criteria)
    store = get_account_store(settings.accounts_db_path)
    updated = store.update_saved_search(
        ctx.user_id,
        saved_search_id,
        name=body.name.strip() if body.name is not None else None,
        criteria=body.criteria.model_dump(mode="json") if body.criteria is not None else None,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found.")
    return {"saved_search": _serialize_saved_search(updated)}


@router.delete("/{saved_search_id}")
def delete_saved_search(
    saved_search_id: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, bool]:
    _require_saved_search_access(ctx)
    store = get_account_store(settings.accounts_db_path)
    if not store.delete_saved_search(ctx.user_id, saved_search_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found.")
    return {"ok": True}
