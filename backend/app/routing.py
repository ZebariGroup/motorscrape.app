"""Path prefix for FastAPI when mounted under a Vercel service route (e.g. /server)."""

from __future__ import annotations

import os


def api_path_prefix() -> str:
    raw = os.environ.get("MOTORSCRAPE_API_PREFIX", "").strip().rstrip("/")
    return raw if raw else ""
