"""Path prefix for FastAPI when mounted under a Vercel service route (e.g. /server)."""

from __future__ import annotations

import os


def api_path_prefix() -> str:
    raw = os.environ.get("MOTORSCRAPE_API_PREFIX", "").strip().rstrip("/")
    if raw:
        return raw
    # On Vercel, project `env` in vercel.json may not reach the Python service; the
    # platform still routes `/server/*` here with the full path prefix (see Vercel Services).
    if os.environ.get("VERCEL"):
        return "/server"
    return ""
