import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _default_accounts_db_path() -> str:
    if os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV")):
        return "/tmp/motorscrape-accounts.sqlite3"
    data_dir = _BACKEND_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "accounts.sqlite3")


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


def _default_places_cache_path() -> str:
    if os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV")):
        return "/tmp/motorscrape-places-cache.sqlite3"
    data_dir = _BACKEND_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "places-cache.sqlite3")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_BACKEND_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Max concurrent Place Details requests when Text Search omits websiteUri.
    places_details_max_concurrency: int = 8
    # Cap website detail lookups per search so broad Places runs do not fan out
    # into unbounded follow-up calls when discovery already found enough candidates.
    places_details_budget_per_search: int = 12

    # Accept GOOGLE_PLACES_API_KEY or the common Google Cloud console name for a Maps/Places key.

    google_places_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GOOGLE_PLACES_API_KEY",
            "GOOGLE_MAPS_API_KEY",
        ),
    )
    # Remove websiteUri from Text Search by default so discovery stays on the cheaper Pro SKU.
    places_discovery_include_website_uri: bool = False
    # Bound how many searchText variants we try per search before we start scraping.
    places_text_query_variant_cap: int = 1
    # Only retry car searches without the strict includedType when the first pass returned very little.
    places_untyped_fallback_result_threshold: int = 0
    # Multiplier used to gather extra dealership candidates before route/cache scoring trims the list.
    places_candidate_limit_multiplier: int = 2
    # Max number of Places Text Search pages to fetch per query (1 = no pagination, 20 results;
    # 2 = up to 40 results; 3 = up to 60).  Each extra page costs one additional API call.
    places_max_page_count: int = 2
    # Explicit user radius choices should always enforce distance; the UI minimum is 5 miles.
    places_geocode_min_radius_miles: int = 5
    places_cache_enabled: bool = True
    places_cache_path: str = Field(default_factory=_default_places_cache_path)
    places_search_cache_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    # Empty result sets are useful as a short negative cache, but keep them brief so
    # transient Places/filtering misses do not suppress legitimate retries for days.
    places_search_empty_cache_ttl_seconds: int = 60 * 60 * 6  # 6 hours
    places_details_cache_ttl_seconds: int = 60 * 60 * 24 * 45  # 45 days
    places_geocode_cache_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days
    places_supabase_region_cache_max_age_days: int = 30
    # If no cached dealer is within this many miles of the search center, the Supabase
    # result set likely comes from a broader prior search that didn't cover the local area.
    # Treat it as a cache miss so Google Places can surface nearby dealers like Brighton Ford
    # or Atchinson Ford (Belleville).  5 miles keeps the check tight enough to avoid false
    # "covered" states in dense suburban markets where other dealers sit 6–15 miles away.
    places_supabase_local_coverage_miles: int = 5
    search_running_window_seconds: int = 60 * 10
    # Ignore orphaned runs that never progressed past startup when enforcing
    # concurrent-search quota, without force-failing them on the next request.
    search_startup_stale_seconds: int = 60 * 2
    # Any run still "running" after this many seconds is considered abandoned
    # (e.g. client disconnected without the backend detecting it) and will not
    # block new searches.  Should be comfortably above the longest expected
    # search duration (dealership_timeout × max_dealerships + buffer).
    search_max_run_age_seconds: int = 60 * 7
    alerts_due_claim_ttl_seconds: int = 60 * 10
    openai_api_key: str = ""
    # LLM model used for extraction; keep this fast for stream responsiveness.
    # Override with OPENAI_EXTRACTION_MODEL (e.g. gpt-5.4-nano for lowest latency/cost).
    openai_extraction_model: str = "gpt-5.4-mini"
    # Seconds; bounds slow/hung LLM calls so the search stream can finish.
    openai_timeout: float = 75.0
    # Cap concurrent OpenAI extraction calls across dealerships (rate limits / tail latency).
    openai_max_concurrency: int = 6
    zenrows_api_key: str = ""
    # Some ZenRows plans do not include premium proxies; leave off unless needed.
    zenrows_premium_proxy: bool = False
    # Milliseconds to wait after JS render (only when js_render=true); lower saves time/credits.
    zenrows_wait_ms: int = 2500
    # Max concurrent in-flight ZenRows API calls. Default to the current Start-tier
    # capacity so production can use the upgraded pool without extra env tuning.
    zenrows_max_concurrency: int = 50
    # Retry transient ZenRows transport/rate-limit failures with small backoff.
    zenrows_request_attempts: int = 2
    zenrows_retry_backoff_ms: int = 1200
    # Brief cooldown after sustained ZenRows throttling to avoid stampedes/cost spikes.
    zenrows_cooldown_seconds: int = 15
    scrapingbee_api_key: str = ""
    scrapingbee_wait_ms: int = 2500
    scrapingbee_max_concurrency: int = 4
    # Shared cap across managed providers (ZenRows + ScrapingBee). Keep this aligned
    # with the upgraded ZenRows plan so the aggregate gate is not the bottleneck.
    managed_scraper_max_concurrency: int = 50
    # Homepage fetches do not usually need JS rendering; keep off to reduce managed spend.
    homepage_managed_js_render: bool = False
    # Self-hosted headless Chromium (Playwright). Runs after direct HTTP fails or HTML is
    # insufficient, before ZenRows/ScrapingBee. Requires `playwright install chromium` on the host.
    playwright_enabled: bool = False
    # Raise local browser fan-out so one slow dealership does not stall unrelated ones.
    playwright_max_workers: int = 4
    playwright_timeout_ms: int = 15_000
    # Baseline settle wait before any platform-specific Playwright interaction recipe runs.
    playwright_post_load_wait_ms: int = 2500
    # Optional proxy server for Playwright (e.g. "http://user:pass@proxy.example.com:8080").
    # Helps bypass WAFs on strict dealer sites without paying for ZenRows/ScrapingBee.
    playwright_proxy_url: str = ""

    # Max dealerships per search (quality vs speed tradeoff).
    max_dealerships: int = 8
    # Concurrent dealership workers (I/O-bound scraping). Higher keeps unrelated dealers moving
    # when a few sites are slow or blocked.
    search_concurrency: int = 8
    # When managed scrapers are enabled, bound worker fan-out by external capacity.
    search_workers_per_managed_slot: int = 2
    # Max concurrent HTTP fetches per normalized dealer domain (avoids hammering shared infra).
    domain_fetch_concurrency: int = 1
    # Hard cap per dealer so one slow site cannot block final completion.
    dealership_timeout: float = 150.0
    # Max pages to follow per dealership inventory (default raised for better SRP coverage).
    max_pages_per_dealer: int = 3
    # Absolute safety cap for auto-pagination. Each page fetch can take 10-30s through
    # managed scrapers, so this must stay low enough to fit within dealership_timeout.
    search_max_pages_per_dealer_cap: int = 12
    # Blend factor for per-dealer scrape score updates. Higher values react faster to recent runs.
    dealer_score_ema_alpha: float = 0.35
    # Use observed search economics as a soft ceiling once the search already has enough
    # useful results; this helps weaker dealers fall back to cheaper paths earlier.
    search_cost_soft_limit_units: float = 28.0
    search_managed_fetch_budget: int = 18
    search_llm_page_budget: int = 12
    search_budget_relief_vehicle_target: int = 40
    search_budget_relief_dealer_target: int = 2
    dealer_score_budget_low_threshold: float = 40.0
    dealer_failure_streak_budget_threshold: int = 2
    # Room58/Harley dealer SRPs often expose very large inventories and paginate cheaply over
    # direct HTTP; allow a higher safety cap only for Harley-focused searches.
    harley_search_max_pages_per_dealer_cap: int = 24
    # Max HTML chars sent to the LLM per page (smaller = cheaper/faster).
    max_html_chars: int = 60_000
    # HTTP timeout for each scraper call (seconds). Keep this moderate so stuck sites fail fast.
    scrape_timeout: float = 30.0
    # Free VIN decoding via the NHTSA vPIC API. Used to fill missing specs like
    # trim, body style, drivetrain, engine, and transmission when a valid VIN is available.
    vin_decoder_enabled: bool = True
    vin_decoder_timeout: float = 8.0
    vin_decoder_max_concurrency: int = 8
    vin_decoder_cache_ttl_seconds: int = 60 * 60 * 24 * 14

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
    inventory_cache_ttl_seconds: int = 60 * 60 * 4
    inventory_cache_stale_revalidate_seconds: int = 60 * 60 * 8
    inventory_cache_path: str = Field(default_factory=_default_inventory_cache_path)

    # Supabase configuration
    supabase_url: str = Field(default="", validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"))
    supabase_anon_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_ANON_KEY",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
        ),
    )
    supabase_service_key: str = Field(default="", validation_alias=AliasChoices("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"))

    session_secret: str = Field(default="", validation_alias=AliasChoices("SESSION_SECRET", "MOTORSCRAPE_SESSION_SECRET"))
    session_max_age_days: int = 14
    accounts_db_path: str = Field(
        default_factory=_default_accounts_db_path,
        validation_alias=AliasChoices("ACCOUNTS_DB_PATH", "MOTORSCRAPE_ACCOUNTS_DB"),
    )

    stripe_secret_key: str = Field(default="", validation_alias=AliasChoices("STRIPE_SECRET_KEY"))
    stripe_webhook_secret: str = Field(default="", validation_alias=AliasChoices("STRIPE_WEBHOOK_SECRET"))
    stripe_price_standard_base: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_STANDARD_BASE"),
    )
    stripe_price_standard_metered: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_STANDARD_METERED"),
    )
    stripe_price_premium_base: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_PREMIUM_BASE"),
    )
    stripe_price_premium_metered: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_PREMIUM_METERED"),
    )
    stripe_price_max_pro_base: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_MAX_PRO_BASE"),
    )
    public_web_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("PUBLIC_WEB_URL", "NEXT_PUBLIC_SITE_URL"),
    )
    resend_api_key: str = Field(default="", validation_alias=AliasChoices("RESEND_API_KEY"))
    alerts_from_email: str = Field(default="", validation_alias=AliasChoices("ALERTS_FROM_EMAIL"))
    alerts_internal_secret: str = Field(default="", validation_alias=AliasChoices("ALERTS_INTERNAL_SECRET"))
    admin_emails: str = Field(default="", validation_alias=AliasChoices("ADMIN_EMAILS", "MOTORSCRAPE_ADMIN_EMAILS"))
    enabled_vehicle_categories: str = Field(
        default="car",
        validation_alias=AliasChoices(
            "ENABLED_VEHICLE_CATEGORIES",
            "MOTORSCRAPE_ENABLED_VEHICLE_CATEGORIES",
        ),
    )


settings = Settings()


def enabled_vehicle_categories() -> set[str]:
    raw = (settings.enabled_vehicle_categories or "car").strip()
    values = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return values or {"car"}


def vehicle_category_enabled(category: str) -> bool:
    return (category or "car").strip().lower() in enabled_vehicle_categories()


def configured_admin_emails() -> set[str]:
    raw = (settings.admin_emails or "").strip()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}
