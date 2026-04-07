"""Shared structured error payloads for search and quota flows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(slots=True)
class SearchErrorInfo:
    code: str
    message: str
    phase: str
    status: str = "failed"
    retryable: bool = False
    upgrade_required: bool = False
    upgrade_tier: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] | None = None

    def with_correlation_id(self, correlation_id: str | None) -> "SearchErrorInfo":
        if correlation_id == self.correlation_id:
            return self
        return replace(self, correlation_id=correlation_id)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "phase": self.phase,
            "status": self.status,
            "retryable": self.retryable,
            "upgrade_required": self.upgrade_required,
        }
        if self.upgrade_tier:
            payload["upgrade_tier"] = self.upgrade_tier
        if self.correlation_id:
            payload["correlation_id"] = self.correlation_id
        if self.details:
            payload["details"] = dict(self.details)
        return payload

    def to_summary(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload.pop("correlation_id", None)
        return payload


def with_search_error(summary: dict[str, Any], error: SearchErrorInfo) -> dict[str, Any]:
    next_summary = dict(summary)
    next_summary["error"] = error.to_summary()
    next_summary["error_message"] = error.message
    next_summary["error_code"] = error.code
    next_summary["error_phase"] = error.phase
    return next_summary


def extract_search_error(summary: Any) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    nested = summary.get("error")
    if isinstance(nested, dict) and nested.get("message") and nested.get("code"):
        payload = dict(nested)
        payload.setdefault("message", str(summary.get("error_message") or ""))
        payload.setdefault("code", str(summary.get("error_code") or ""))
        payload.setdefault("phase", str(summary.get("error_phase") or payload.get("phase") or "search"))
        return payload
    message = str(summary.get("error_message") or "").strip()
    if not message:
        return None
    code = str(summary.get("error_code") or "search.unknown_failure").strip() or "search.unknown_failure"
    phase = str(summary.get("error_phase") or "search").strip() or "search"
    return {
        "code": code,
        "message": message,
        "phase": phase,
        "status": str(summary.get("status") or "failed") or "failed",
        "retryable": False,
        "upgrade_required": False,
    }
