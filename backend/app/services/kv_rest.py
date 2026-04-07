"""Small helper for Vercel KV / Upstash REST JSON access."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class KvRestStore:
    def enabled(self) -> bool:
        return bool((settings.kv_rest_api_url or "").strip() and (settings.kv_rest_api_token or "").strip())

    def _base_url(self) -> str:
        return (settings.kv_rest_api_url or "").strip().rstrip("/")

    def _token(self) -> str:
        return (settings.kv_rest_api_token or "").strip()

    def execute(self, command: list[Any]) -> object | None:
        base = self._base_url()
        token = self._token()
        if not base or not token:
            return None
        try:
            with httpx.Client(timeout=httpx.Timeout(12.0)) as client:
                response = client.post(
                    base,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=command,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and "result" in payload:
                    return payload["result"]
                logger.debug("Unexpected KV REST response for %s: %s", command[:1], payload)
                return None
        except Exception as exc:
            logger.warning("KV REST request failed (%s): %s", command[:1] if command else "?", exc)
            return None

    def get_json(self, key: str) -> Any | None:
        raw = self.execute(["GET", key])
        if raw is None:
            return None
        if not isinstance(raw, str):
            logger.debug("KV GET returned non-string for %s", key)
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("KV value is not valid JSON for %s", key)
            return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        encoded = json.dumps(value, default=str, sort_keys=True)
        result = self.execute(["SET", key, encoded, "EX", max(1, int(ttl_seconds or 0))])
        if result not in ("OK", True, None) and result is not None:
            logger.debug("Unexpected KV SET result for %s: %s", key, result)

    def delete(self, key: str) -> None:
        self.execute(["DEL", key])


kv_rest_store = KvRestStore()
