"""Shared pytest configuration."""

from __future__ import annotations

import os

# Avoid reading a real .env during tests; tests set env vars explicitly when needed.
os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-places-key-not-used")
os.environ.setdefault("OPENAI_API_KEY", "")
