"""
Vercel FastAPI entrypoint.

The ASGI `app` must live at this path for the `api` service in vercel.json.
"""

from app.main import app  # noqa: F401
