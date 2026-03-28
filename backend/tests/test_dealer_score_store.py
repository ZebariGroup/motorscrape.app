from pathlib import Path
from types import SimpleNamespace

import app.services.dealer_score_store as dealer_score_store
import pytest


def test_record_scrape_outcome_creates_initial_score(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "dealer-scores.sqlite3"
    monkeypatch.setattr(
        dealer_score_store,
        "settings",
        SimpleNamespace(
            platform_cache_path=str(db),
            dealer_score_ema_alpha=0.35,
        ),
    )

    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=50,
        price_fill=1.0,
        vin_fill=1.0,
        elapsed_s=20.0,
        failed=False,
    )

    scores = dealer_score_store.get_scores(["dealer.example"])
    assert scores["dealer.example"] == 100.0


def test_record_scrape_outcome_applies_ema(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "dealer-scores.sqlite3"
    monkeypatch.setattr(
        dealer_score_store,
        "settings",
        SimpleNamespace(
            platform_cache_path=str(db),
            dealer_score_ema_alpha=0.35,
        ),
    )

    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=50,
        price_fill=1.0,
        vin_fill=1.0,
        elapsed_s=20.0,
        failed=False,
    )
    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=0,
        price_fill=0.0,
        vin_fill=0.0,
        elapsed_s=200.0,
        failed=True,
    )

    scores = dealer_score_store.get_scores(["dealer.example"])
    assert scores["dealer.example"] == 65.0


def test_record_scrape_outcome_tracks_failure_streak(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "dealer-scores.sqlite3"
    monkeypatch.setattr(
        dealer_score_store,
        "settings",
        SimpleNamespace(
            platform_cache_path=str(db),
            dealer_score_ema_alpha=0.35,
        ),
    )

    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=0,
        price_fill=0.0,
        vin_fill=0.0,
        elapsed_s=200.0,
        failed=True,
    )
    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=0,
        price_fill=0.0,
        vin_fill=0.0,
        elapsed_s=200.0,
        failed=True,
    )

    conn = dealer_score_store._connect(str(db))
    assert conn is not None
    try:
        row = conn.execute(
            "SELECT run_count, failure_streak FROM dealer_scores WHERE domain = ?",
            ("dealer.example",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert int(row["run_count"]) == 2
    assert int(row["failure_streak"]) == 2


def test_record_scrape_outcome_resets_failure_streak_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "dealer-scores.sqlite3"
    monkeypatch.setattr(
        dealer_score_store,
        "settings",
        SimpleNamespace(
            platform_cache_path=str(db),
            dealer_score_ema_alpha=0.35,
        ),
    )

    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=0,
        price_fill=0.0,
        vin_fill=0.0,
        elapsed_s=200.0,
        failed=True,
    )
    dealer_score_store.record_scrape_outcome(
        "dealer.example",
        listings=25,
        price_fill=0.5,
        vin_fill=0.5,
        elapsed_s=60.0,
        failed=False,
    )

    conn = dealer_score_store._connect(str(db))
    assert conn is not None
    try:
        row = conn.execute(
            "SELECT failure_streak FROM dealer_scores WHERE domain = ?",
            ("dealer.example",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert int(row["failure_streak"]) == 0


def test_get_scores_returns_known_domains_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "dealer-scores.sqlite3"
    monkeypatch.setattr(
        dealer_score_store,
        "settings",
        SimpleNamespace(
            platform_cache_path=str(db),
            dealer_score_ema_alpha=0.35,
        ),
    )

    dealer_score_store.record_scrape_outcome(
        "dealer-one.example",
        listings=10,
        price_fill=0.2,
        vin_fill=0.4,
        elapsed_s=45.0,
        failed=False,
    )

    scores = dealer_score_store.get_scores(["dealer-one.example", "dealer-two.example"])
    assert "dealer-one.example" in scores
    assert "dealer-two.example" not in scores
