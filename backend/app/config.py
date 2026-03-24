from pathlib import Path

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

    google_places_api_key: str = ""
    openai_api_key: str = ""
    zenrows_api_key: str = ""
    scrapingbee_api_key: str = ""

    # Max dealerships per search (quality vs speed tradeoff)
    max_dealerships: int = 8
    # Max HTML chars sent to the LLM per page
    max_html_chars: int = 120_000
    # HTTP timeout for scraper (seconds)
    scrape_timeout: float = 45.0


settings = Settings()
