"""FastAPI dependencies: client identity, sessions, tier resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Header, HTTPException, Request, status

from app.auth.session import SESSION_COOKIE_NAME, read_session_token
from app.config import configured_admin_emails, settings
from app.db.account_store import get_account_store
from app.tiers import TierId, TierLimits, limits_for_tier


def _client_ip(request: Request, x_forwarded_for: str | None, x_real_ip: str | None) -> str:
    if x_real_ip:
        return x_real_ip.strip()
    if x_forwarded_for:
        # If spoofed, the real IP added by the proxy is typically the last or rightmost trusted one.
        # For Vercel, x-real-ip is safer. If we only have x-forwarded-for, we take the first as a fallback,
        # but note it can be spoofed if not stripped by the edge.
        return x_forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def anon_key_for_request(request: Request, x_forwarded_for: str | None, x_real_ip: str | None) -> str:
    ip = _client_ip(request, x_forwarded_for, x_real_ip)
    pepper = (settings.session_secret or "dev-insecure-pepper").encode()
    return hashlib.sha256(pepper + b"|" + ip.encode()).hexdigest()[:32]


@dataclass(slots=True)
class AccessContext:
    tier: str
    limits: TierLimits
    user_id: str | None
    email: str | None
    anon_key: str | None
    is_admin: bool


def _is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in configured_admin_emails()


def get_access_context(
    request: Request,
    x_forwarded_for: Annotated[str | None, Header(alias="X-Forwarded-For")] = None,
    x_real_ip: Annotated[str | None, Header(alias="X-Real-IP")] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AccessContext:
    store = get_account_store(settings.accounts_db_path)
    uid = read_session_token(session_token)
    if uid is not None:
        user = store.get_user_by_id(uid)
        if user:
            lim = limits_for_tier(user.tier)
            return AccessContext(
                tier=user.tier,
                limits=lim,
                user_id=user.id,
                email=user.email,
                anon_key=None,
                is_admin=bool(user.is_admin or _is_admin_email(user.email)),
            )
    ak = anon_key_for_request(request, x_forwarded_for, x_real_ip)
    return AccessContext(
        tier=TierId.ANONYMOUS.value,
        limits=limits_for_tier(TierId.ANONYMOUS.value),
        user_id=None,
        email=None,
        anon_key=ak,
        is_admin=False,
    )


def require_admin_context(ctx: AccessContext) -> AccessContext:
    if ctx.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    if not ctx.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required.")
    return ctx
