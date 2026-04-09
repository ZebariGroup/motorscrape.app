from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from app.services.scrape_logging import ScrapeRunRecorder


class _EventFailingStore:
    def add_scrape_event(self, **kwargs: Any) -> None:
        raise RuntimeError("event write failed")


class _FlakyFinalizeStore:
    def __init__(self) -> None:
        self.finalize_calls = 0
        self.last_finalize_kwargs: dict[str, Any] | None = None
        self.history_calls = 0

    def finalize_scrape_run(self, run_id: str, **kwargs: Any) -> Any:
        self.finalize_calls += 1
        if self.finalize_calls == 1:
            raise RuntimeError("transient finalize failure")
        self.last_finalize_kwargs = kwargs
        return SimpleNamespace(id=run_id)

    def record_inventory_history(self, *_args: Any, **_kwargs: Any) -> None:
        self.history_calls += 1


def test_event_does_not_raise_when_store_write_fails() -> None:
    recorder = ScrapeRunRecorder(
        store=_EventFailingStore(),
        run_id="run-1",
        correlation_id="srch-123",
        trigger_source="interactive",
        started_at=time.time(),
    )

    recorder.event(
        event_type="search_started",
        phase="startup",
        level="info",
        message="Search started.",
    )

    assert recorder.sequence_no == 1
    assert recorder.error_count == 0


def test_finalize_can_retry_after_initial_store_failure() -> None:
    store = _FlakyFinalizeStore()
    recorder = ScrapeRunRecorder(
        store=store,
        run_id="run-1",
        correlation_id="srch-123",
        trigger_source="interactive",
        started_at=time.time(),
    )

    recorder.finalize(
        ok=False,
        status="failed",
        summary={"ok": False, "status": "failed"},
        economics={},
        error_message="first attempt failed",
    )

    assert recorder.finalized is False
    assert store.finalize_calls == 1

    recorder.finalize(
        ok=False,
        status="failed",
        summary={"ok": False, "status": "failed"},
        economics={},
        error_message="first attempt failed",
    )

    assert recorder.finalized is True
    assert store.finalize_calls == 2
    assert store.last_finalize_kwargs is not None
    assert store.last_finalize_kwargs["status"] == "failed"
