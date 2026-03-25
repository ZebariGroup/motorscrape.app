import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _default_inventory_cache_path() -> str:
    if os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV")):
        return "/tmp/motorscrape-inventory-cache.sqlite3"
    data_dir = _BACKEND_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "inventory-cache.sqlite3")


def _default_platform_cache_path() -> str:
    """Vercel filesystem is ephemeral — /tmp is appropriate. Local dev uses repo-local sqlite."""
    if os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV")):
        return "/tmp/motorscrape-platform-cache.sqlite3"
    data_dir = _BACKEND_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "platform-cache.sqlite3")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_BACKEND_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Accept GOOGLE_PLACES_API_KEY or the common Google Cloud console name for a Maps/Places key.
    google_places_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GOOGLE_PLACES_API_KEY",
            "GOOGLE_MAPS_API_KEY",
        ),
    )
    openai_api_key: str = ""
    # LLM model used for extraction; keep this fast for stream responsiveness.
    openai_extraction_model: str = "gpt-4o-mini"
    # Seconds; bounds slow/hung LLM calls so the search stream can finish.
    openai_timeout: float = 75.0
    zenrows_api_key: str = ""
    # Some ZenRows plans do not include premium proxies; leave off unless needed.
    zenrows_premium_proxy: bool = False
    # Milliseconds to wait after JS render (only when js_render=true); lower saves time/credits.
    zenrows_wait_ms: int = 3000
    scrapingbee_api_key: str = ""
    scrapingbee_wait_ms: int = 3000
    # Self-hosted headless Chromium (Playwright). Runs after direct HTTP fails or HTML is
    # insufficient, before ZenRows/ScrapingBee. Requires `playwright install chromium` on the host.
    playwright_enabled: bool = False
    playwright_max_workers: int = 2
    playwright_timeout_ms: int = 45_000
    playwright_post_load_wait_ms: int = 2500

    # Max dealerships per search (quality vs speed tradeoff).
    max_dealerships: int = 8
    # Concurrent dealership workers (I/O-bound scraping).
    search_concurrency: int = 5
    # Max concurrent HTTP fetches per normalized dealer domain (avoids hammering shared infra).
    domain_fetch_concurrency: int = 1
    # Hard cap per dealer so one slow site cannot block final completion.
    dealership_timeout: float = 150.0
    # Max pages to follow per dealership inventory (default raised for better SRP coverage).
    max_pages_per_dealer: int = 3
    # Hard cap for API/query overrides so one search cannot paginate unbounded on serverless.
    search_max_pages_per_dealer_cap: int = 10
    # Max HTML chars sent to the LLM per page (smaller = cheaper/faster).
    max_html_chars: int = 60_000
    # HTTP timeout for each scraper call (seconds).
    scrape_timeout: float = 90.0
    # Platform detection cache. Override PLATFORM_CACHE_PATH on Vercel if using persistent storage.
    platform_cache_enabled: bool = True
    platform_cache_path: str = Field(default_factory=_default_platform_cache_path)
    platform_cache_ttl_hours: int = 24 * 14
    platform_cache_failure_threshold: int = 3

    # Vercel KV / Upstash REST — when both are set, platform detection cache uses Redis instead of SQLite.
    # https://vercel.com/docs/storage/vercel-kv (same REST shape as Upstash)
    kv_rest_api_url: str = ""
    kv_rest_api_token: str = ""

    # Short-lived cache of per-dealer listing payloads (SQLite).
    inventory_cache_enabled: bool = True
    inventory_cache_ttl_seconds: int = 3600
    inventory_cache_path: str = Field(default_factory=_default_inventory_cache_path)


settings = Settings()
