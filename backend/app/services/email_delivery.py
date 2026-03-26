from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass(slots=True)
class EmailAttachment:
    filename: str
    content_type: str
    content_bytes: bytes


def email_delivery_configured() -> bool:
    return bool(settings.resend_api_key and settings.alerts_from_email)


async def send_email(
    *,
    to_email: str,
    subject: str,
    html: str,
    text: str,
    attachments: list[EmailAttachment] | None = None,
) -> dict[str, Any]:
    if not email_delivery_configured():
        raise RuntimeError("Email delivery is not configured.")

    payload: dict[str, Any] = {
        "from": settings.alerts_from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment.filename,
                "content": base64.b64encode(attachment.content_bytes).decode("ascii"),
                "type": attachment.content_type,
            }
            for attachment in attachments
        ]

    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("https://api.resend.com/emails", headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    return dict(data) if isinstance(data, dict) else {"ok": True}
