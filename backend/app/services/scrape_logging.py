from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_SCRAPE_EVENTS = 200
MAX_LISTINGS_SNAPSHOT = 10_000


def build_correlation_id(*, prefix: str = "srch") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def derive_run_status(*, ok: bool, dealerships_failed: int, error_count: int, warning_count: int) -> str:
    if not ok:
        return "failed"
    if dealerships_failed > 0 or error_count > 0:
        return "partial_failure"
    return "success"


def _log_level_name(level: str) -> int:
    if level == "error":
        return logging.ERROR
    if level == "warning":
        return logging.WARNING
    return logging.INFO


@dataclass(slots=True)
class ScrapeRunRecorder:
    store: Any
    run_id: str
    correlation_id: str
    trigger_source: str
    started_at: float
    user_id: str | None = None
    persist_listing_snapshot: bool = False
    max_events: int = MAX_SCRAPE_EVENTS
    sequence_no: int = 0
    error_count: int = 0
    warning_count: int = 0
    dealerships_attempted: int = 0
    dealerships_succeeded: int = 0
    dealerships_failed: int = 0
    result_count: int = 0
    latest_error_message: str | None = None
    finalized: bool = False
    _overflow_logged: bool = False
    _seen_dealers: set[str] = field(default_factory=set)
    first_discovered_dealer_ms: int | None = None
    first_active_dealer_ms: int | None = None
    first_vehicle_batch_ms: int | None = None
    timeout_counts_by_platform: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    timeout_counts_by_fetch_method: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_counts_by_platform: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_counts_by_fetch_method: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _listings_snapshot: list[dict[str, Any]] = field(default_factory=list)
    _listings_lock: threading.Lock = field(default_factory=threading.Lock)

    def _elapsed_ms(self) -> int:
        return max(0, int((time.time() - self.started_at) * 1000))

    def _mark_first(self, field_name: str) -> None:
        if getattr(self, field_name) is None:
            setattr(self, field_name, self._elapsed_ms())

    @staticmethod
    def _bump(counter: dict[str, int], key: str | None) -> None:
        normalized = (key or "unknown").strip() or "unknown"
        counter[normalized] = int(counter.get(normalized, 0)) + 1

    def event(
        self,
        *,
        event_type: str,
        message: str,
        phase: str | None = None,
        level: str = "info",
        dealership_name: str | None = None,
        dealership_website: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event_payload = dict(payload or {})
        created_at = time.time()
        self.sequence_no += 1
        if level == "error":
            self.error_count += 1
            self.latest_error_message = message
        elif level == "warning":
            self.warning_count += 1
            self.latest_error_message = self.latest_error_message or message
        event_record = {
            "correlation_id": self.correlation_id,
            "event_type": event_type,
            "phase": phase,
            "level": level,
            "message": message,
            "dealership_name": dealership_name,
            "dealership_website": dealership_website,
            "payload": event_payload,
            "sequence_no": self.sequence_no,
        }
        logger.log(
            _log_level_name(level),
            "scrape_event type=%s phase=%s cid=%s %s",
            event_type,
            phase or "-",
            self.correlation_id,
            message,
            extra={"scrape_event": event_record},
        )
        if self.sequence_no <= self.max_events:
            self.store.add_scrape_event(
                scrape_run_id=self.run_id,
                correlation_id=self.correlation_id,
                sequence_no=self.sequence_no,
                event_type=event_type,
                phase=phase,
                level=level,
                message=message,
                dealership_name=dealership_name,
                dealership_website=dealership_website,
                payload=event_payload,
                created_at=created_at,
            )
            return
        if not self._overflow_logged:
            self._overflow_logged = True
            self.store.add_scrape_event(
                scrape_run_id=self.run_id,
                correlation_id=self.correlation_id,
                sequence_no=self.max_events,
                event_type="event_overflow",
                phase="logging",
                level="warning",
                message="Additional scrape events were dropped after reaching the cap.",
                dealership_name=None,
                dealership_website=None,
                payload={"max_events": self.max_events},
                created_at=created_at,
            )

    def note_dealer_started(self, *, dealership_name: str, dealership_website: str | None = None) -> None:
        dealer_key = dealership_website or dealership_name
        if dealer_key not in self._seen_dealers:
            self._seen_dealers.add(dealer_key)
            self.dealerships_attempted += 1
        self._mark_first("first_active_dealer_ms")

    def note_dealer_discovered(self) -> None:
        self._mark_first("first_discovered_dealer_ms")

    def note_dealer_done(self, *, listings_found: int) -> None:
        self.dealerships_succeeded += 1
        self.result_count += max(0, int(listings_found))

    def note_dealer_failed(self) -> None:
        self.dealerships_failed += 1

    def note_vehicle_batch(
        self,
        *,
        batch_size: int,
        platform_id: str | None = None,
        fetch_method: str | None = None,
    ) -> None:
        if batch_size > 0:
            self._mark_first("first_vehicle_batch_ms")

    def capture_listing_batch(self, *, dealership: str, website: str, listings: list[dict[str, Any]]) -> None:
        if not self.persist_listing_snapshot or not listings:
            return
        with self._listings_lock:
            room = MAX_LISTINGS_SNAPSHOT - len(self._listings_snapshot)
            if room <= 0:
                return
            for raw in listings[:room]:
                row = dict(raw)
                if not (row.get("dealership") or "").strip():
                    row["dealership"] = dealership
                if not (row.get("dealership_website") or "").strip():
                    row["dealership_website"] = website
                self._listings_snapshot.append(row)
                room -= 1
                if room <= 0:
                    break

    def note_dealer_issue(
        self,
        *,
        issue_type: str,
        platform_id: str | None = None,
        fetch_method: str | None = None,
    ) -> None:
        if issue_type == "timeout":
            self._bump(self.timeout_counts_by_platform, platform_id)
            self._bump(self.timeout_counts_by_fetch_method, fetch_method)
            return
        self._bump(self.error_counts_by_platform, platform_id)
        self._bump(self.error_counts_by_fetch_method, fetch_method)

    def summary_metrics(self) -> dict[str, Any]:
        return {
            "timing_metrics_ms": {
                "first_discovered_dealer": self.first_discovered_dealer_ms,
                "first_active_dealer": self.first_active_dealer_ms,
                "first_vehicle_batch": self.first_vehicle_batch_ms,
            },
            "dealer_issue_breakdown": {
                "timeouts_by_platform": dict(sorted(self.timeout_counts_by_platform.items())),
                "timeouts_by_fetch_method": dict(sorted(self.timeout_counts_by_fetch_method.items())),
                "errors_by_platform": dict(sorted(self.error_counts_by_platform.items())),
                "errors_by_fetch_method": dict(sorted(self.error_counts_by_fetch_method.items())),
            },
        }

    def finalize(
        self,
        *,
        ok: bool,
        summary: dict[str, Any],
        economics: dict[str, Any],
        error_message: str | None = None,
        status: str | None = None,
    ) -> None:
        if self.finalized:
            return
        self.finalized = True
        final_status = status or derive_run_status(
            ok=ok,
            dealerships_failed=self.dealerships_failed,
            error_count=self.error_count,
            warning_count=self.warning_count,
        )
        self.latest_error_message = error_message or self.latest_error_message
        with self._listings_lock:
            listings_snapshot = (
                list(self._listings_snapshot)
                if self.persist_listing_snapshot and self._listings_snapshot
                else None
            )
        completed_at = time.time()
        self.store.finalize_scrape_run(
            self.run_id,
            status=final_status,
            result_count=self.result_count,
            dealer_discovery_count=summary.get("dealer_discovery_count"),
            dealer_deduped_count=summary.get("dealer_deduped_count"),
            dealerships_attempted=self.dealerships_attempted,
            dealerships_succeeded=self.dealerships_succeeded,
            dealerships_failed=self.dealerships_failed,
            error_count=self.error_count,
            warning_count=self.warning_count,
            error_message=self.latest_error_message,
            summary=summary,
            economics=economics,
            completed_at=completed_at,
            listings_snapshot=listings_snapshot,
        )
        if self.user_id is not None and listings_snapshot:
            try:
                self.store.record_inventory_history(
                    self.user_id,
                    scrape_run_id=self.run_id,
                    listings=listings_snapshot,
                    observed_at=completed_at,
                )
            except Exception:
                logger.exception("Failed to record inventory history for run %s", self.run_id)


def create_scrape_run_recorder(
    *,
    store: Any,
    correlation_id: str,
    trigger_source: str,
    location: str,
    make: str,
    model: str,
    vehicle_category: str,
    vehicle_condition: str,
    inventory_scope: str,
    radius_miles: int,
    requested_max_dealerships: int | None,
    requested_max_pages_per_dealer: int | None,
    user_id: str | None = None,
    anon_key: str | None = None,
) -> ScrapeRunRecorder:
    started_at = time.time()
    run = store.create_scrape_run(
        correlation_id=correlation_id,
        user_id=user_id,
        anon_key=anon_key,
        trigger_source=trigger_source,
        status="running",
        location=location,
        make=make,
        model=model,
        vehicle_category=vehicle_category,
        vehicle_condition=vehicle_condition,
        inventory_scope=inventory_scope,
        radius_miles=radius_miles,
        requested_max_dealerships=requested_max_dealerships,
        requested_max_pages_per_dealer=requested_max_pages_per_dealer,
        started_at=started_at,
    )
    return ScrapeRunRecorder(
        store=store,
        run_id=run.id,
        correlation_id=correlation_id,
        trigger_source=trigger_source,
        started_at=started_at,
        user_id=user_id,
        persist_listing_snapshot=trigger_source == "interactive" or trigger_source.startswith("alert_"),
    )
