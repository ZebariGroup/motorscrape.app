"""Signed cookie sessions (works with browser EventSource same-origin requests)."""

from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

SESSION_COOKIE_NAME = "ms_session"


def _serializer() -> URLSafeTimedSerializer:
    secret = (settings.session_secret or "").strip()
    if not secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(secret, salt="motorscrape-session-v1")


def issue_session_token(user_id: str | int) -> str:
    return _serializer().dumps({"uid": str(user_id), "v": 1})


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data: dict[str, Any] = _serializer().loads(
            token,
            max_age=int(settings.session_max_age_days * 86400),
        )
        return str(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
