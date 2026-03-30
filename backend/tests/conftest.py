"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest

# Avoid reading a real .env during tests; tests set env vars explicitly when needed.
os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-places-key-not-used")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("SESSION_SECRET", "pytest-session-secret-key-32b!!")


@pytest.fixture(autouse=True)
def _isolated_accounts_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite DB so anonymous quotas do not leak between cases."""
    db = str(tmp_path / "accounts.sqlite3")
    monkeypatch.setattr("app.config.settings.accounts_db_path", db)
    monkeypatch.setattr("app.config.settings.places_cache_path", str(tmp_path / "places-cache.sqlite3"))
    monkeypatch.setattr("app.config.settings.supabase_url", "")
    monkeypatch.setattr("app.config.settings.supabase_service_key", "")
    import app.db.account_store as account_store_module

    account_store_module._store = None
    yield
    account_store_module._store = None
