from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


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

    # Max dealerships per search (quality vs speed tradeoff).
    max_dealerships: int = 8
    # Concurrent dealership workers.
    search_concurrency: int = 2
    # Hard cap per dealer so one slow site cannot block final completion.
    dealership_timeout: float = 150.0
    # Max pages to follow per dealership inventory.
    max_pages_per_dealer: int = 1
    # Max HTML chars sent to the LLM per page (smaller = cheaper/faster).
    max_html_chars: int = 60_000
    # HTTP timeout for each scraper call (seconds).
    scrape_timeout: float = 90.0
    # Platform detection cache. Use a writable path in the runtime environment.
    platform_cache_enabled: bool = True
    platform_cache_path: str = "/tmp/motorscrape-platform-cache.sqlite3"
    platform_cache_ttl_hours: int = 24 * 14
    platform_cache_failure_threshold: int = 3


settings = Settings()
