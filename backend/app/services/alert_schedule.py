from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalize_timezone(timezone_name: str) -> str:
    candidate = (timezone_name or "").strip() or "UTC"
    try:
        ZoneInfo(candidate)
        return candidate
    except ZoneInfoNotFoundError:
        return "UTC"


def next_run_at_utc(
    *,
    cadence: str,
    hour_local: int,
    timezone_name: str,
    day_of_week: int | None,
    now_utc: datetime | None = None,
) -> datetime:
    tz_name = normalize_timezone(timezone_name)
    tz = ZoneInfo(tz_name)
    now = now_utc or datetime.now(UTC)
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour_local, minute=0, second=0, microsecond=0)

    if cadence == "weekly":
        if day_of_week is None:
            raise ValueError("Weekly alerts require day_of_week.")
        delta_days = (day_of_week - local_now.weekday()) % 7
        candidate = candidate + timedelta(days=delta_days)
        if candidate <= local_now:
            candidate += timedelta(days=7)
    else:
        if candidate <= local_now:
            candidate += timedelta(days=1)

    return candidate.astimezone(UTC)
