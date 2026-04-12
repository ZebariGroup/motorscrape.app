"""Sign-up, login, session, and access summary endpoints."""

from __future__ import annotations

import os
import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AccessContext, get_access_context
from app.auth.session import SESSION_COOKIE_NAME, issue_session_token
from app.config import settings
from app.db.account_store import get_account_store
from app.db.supabase_store import EmailAlreadyRegisteredError, EmailNotVerifiedError
from app.tiers import TierId, limits_for_tier

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignUpBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: str
    password: str


def _period_utc() -> str:
    return time.strftime("%Y-%m", time.gmtime())


def _cookie_secure() -> bool:
    return bool(os.environ.get("VERCEL")) or os.environ.get("ENVIRONMENT", "").lower() == "production"


def _set_session_cookie(resp: Response, user_id: str | int) -> None:
    token = issue_session_token(user_id)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=int(settings.session_max_age_days * 86400),
        path="/",
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignUpBody, response: Response) -> dict[str, Any]:
    if not (settings.session_secret or "").strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Accounts are not configured.")
    if not _EMAIL_RE.match(body.email.strip().lower()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid email.")
    store = get_account_store(settings.accounts_db_path)
    if store.get_user_by_email(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.")
    try:
        user = store.create_user(body.email, body.password, tier=TierId.FREE.value)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.") from None
    except RuntimeError as exc:
        msg = str(exc)
        if "SUPABASE_ANON_KEY" in msg:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, msg) from exc
        raise
    if settings.supabase_url and settings.supabase_service_key:
        # Session is issued only after they confirm the Supabase magic link / OTP.
        return {
            "id": user.id,
            "email": user.email,
            "tier": user.tier,
            "email_verification_required": True,
        }
    _set_session_cookie(response, user.id)
    return {"id": user.id, "email": user.email, "tier": user.tier}


@router.post("/login")
def login(body: LoginBody, response: Response) -> dict[str, Any]:
    if not (settings.session_secret or "").strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Accounts are not configured.")
    store = get_account_store(settings.accounts_db_path)
    try:
        user = store.verify_login(body.email, body.password)
    except EmailNotVerifiedError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm the link in your email before signing in.",
        ) from None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    _set_session_cookie(response, user.id)
    return {"id": user.id, "email": user.email, "tier": user.tier}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    _clear_session_cookie(response)
    return {"ok": True}


class UpdatePasswordBody(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)

@router.post("/update-password")
def update_password(body: UpdatePasswordBody, ctx: Annotated[AccessContext, Depends(get_access_context)]) -> dict[str, bool]:
    if not ctx.user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    store = get_account_store(settings.accounts_db_path)
    store.update_password(ctx.user_id, body.new_password)
    return {"ok": True}

@router.get("/me")
def me(ctx: Annotated[AccessContext, Depends(get_access_context)]) -> dict[str, Any]:
    if ctx.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    store = get_account_store(settings.accounts_db_path)
    user = store.get_user_by_id(ctx.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    period = _period_utc()
    used, over = store.monthly_usage(user.id, period)
    lim = limits_for_tier(user.tier)
    return {
        "id": user.id,
        "email": user.email,
        "tier": user.tier,
        "is_admin": ctx.is_admin,
        "usage": {
            "period": period,
            "included_used": used,
            "overage_used": over,
            "included_limit": lim.included_searches_per_month,
        },
        "limits": {
            "max_dealerships": lim.max_dealerships,
            "max_pages_per_dealer": lim.max_pages_per_dealer,
            "max_radius_miles": lim.max_radius_miles,
            "csv_export": lim.csv_export,
            "inventory_scope_premium": lim.inventory_scope_premium,
        },
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_metered_item_id": bool(user.stripe_metered_item_id),
    }


@router.get("/access-summary")
def access_summary(ctx: Annotated[AccessContext, Depends(get_access_context)]) -> dict[str, Any]:
    lim = ctx.limits
    store = get_account_store(settings.accounts_db_path)
    out: dict[str, Any] = {
        "authenticated": ctx.user_id is not None,
        "tier": ctx.tier,
        "is_admin": ctx.is_admin,
        "limits": {
            "max_dealerships": lim.max_dealerships,
            "max_pages_per_dealer": lim.max_pages_per_dealer,
            "max_radius_miles": lim.max_radius_miles,
            "max_concurrent_searches": lim.max_concurrent_searches,
            "csv_export": lim.csv_export,
            "inventory_scope_premium": lim.inventory_scope_premium,
            "minute_rate_limit": lim.minute_rate_limit,
        },
    }
    if ctx.user_id is None and ctx.anon_key:
        used = store.anon_get(ctx.anon_key)
        cap = lim.anonymous_lifetime_searches
        out["anonymous"] = {
            "searches_used": used,
            "searches_remaining": max(0, cap - used),
            "signup_required_after": cap,
        }
    elif ctx.user_id:
        period = _period_utc()
        used, over = store.monthly_usage(ctx.user_id, period)
        out["usage"] = {
            "period": period,
            "included_used": used,
            "overage_used": over,
            "included_limit": lim.included_searches_per_month,
        }
    return out
