"""HTTP contract tests for the FastAPI app."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.search_quota import SearchQuotaDecision
from app.config import settings
from app.main import app
from app.services.search_errors import SearchErrorInfo
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_root() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_server_prefix() -> None:
    r = client.get("/server/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_vin_details_endpoint_is_public() -> None:
    with patch(
        "app.services.vin_decoder._decode_vin",
        new=AsyncMock(
            return_value={
                "vin": "1FMDE6BH1TLA86328",
                "year": 2026,
                "make": "Ford",
                "model": "Bronco",
                "trim": "Base",
                "body_style": "Utility",
                "drivetrain": "4WD",
                "engine": "2.3L 4-cyl",
                "transmission": "Automatic",
                "fuel_type": "Gasoline",
            }
        ),
    ) as mocked_decode:
        response = client.get("/vehicles/vin-details", params={"vin": "1FMDE6BH1TLA86328"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "vin": "1FMDE6BH1TLA86328",
        "details": {
            "vin": "1FMDE6BH1TLA86328",
            "year": 2026,
            "make": "Ford",
            "model": "Bronco",
            "trim": "Base",
            "body_style": "Utility",
            "transmission": "Automatic",
            "drivetrain": "4WD",
            "fuel_type": "Gasoline",
            "engine": "2.3L 4-cyl",
        },
        "source": "vin_decoder",
    }
    mocked_decode.assert_awaited_once_with("1FMDE6BH1TLA86328")


def test_vin_details_endpoint_returns_empty_payload_when_decode_fails() -> None:
    with patch("app.services.vin_decoder._decode_vin", new=AsyncMock(return_value=None)) as mocked_decode:
        response = client.get("/vehicles/vin-details", params={"vin": "1FMDE6BH1TLA86328"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "vin": "1FMDE6BH1TLA86328",
        "details": {
            "vin": "1FMDE6BH1TLA86328",
        },
        "source": "none",
        "message": "No VIN details found for this vehicle.",
    }
    mocked_decode.assert_awaited_once_with("1FMDE6BH1TLA86328")


def test_search_stream_requires_location() -> None:
    r = client.get("/search/stream")
    assert r.status_code == 422


def test_search_stream_no_dealers_mocked() -> None:
    """SSE returns done without calling Google when Places yields no rows."""
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with client.stream("GET", "/search/stream", params={"location": "XX"}) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes())
    assert b"event: done" in body
    assert b"Finding additional dealerships" in body or b"No dealerships" in body


def test_search_stream_accepts_vehicle_category() -> None:
    # Feature flag defaults to car-only in CI; this test covers param wiring, not gating.
    with patch("app.main.vehicle_category_enabled", return_value=True):
        with patch(
            "app.services.orchestrator.find_dealerships",
            new_callable=AsyncMock,
            return_value=[],
        ) as mocked_find:
            with client.stream(
                "GET",
                "/search/stream",
                params={"location": "XX", "vehicle_category": "boat"},
            ) as r:
                assert r.status_code == 200
                _ = b"".join(r.iter_bytes())
        assert mocked_find.await_args.kwargs["vehicle_category"] == "boat"


def test_search_stream_duplicate_running_correlation_id_returns_204() -> None:
    mocked_store = SimpleNamespace(
        get_scrape_run=lambda correlation_id, *, user_id=None, anon_key=None: SimpleNamespace(status="running"),
    )
    with patch("app.main.get_account_store", return_value=mocked_store):
        with patch("app.main.create_scrape_run_recorder") as mocked_recorder:
            with patch("app.main.evaluate_search_start") as mocked_quota:
                response = client.get(
                    "/search/stream",
                    params={"location": "Detroit, MI", "correlation_id": "srch-duplicate"},
                )
    assert response.status_code == 204
    mocked_recorder.assert_not_called()
    mocked_quota.assert_not_called()


def test_search_stream_blocks_when_too_many_running_searches() -> None:
    mocked_store = SimpleNamespace(
        get_scrape_run=lambda correlation_id, *, user_id=None, anon_key=None: None,
        count_running_scrape_runs=lambda *, user_id=None, anon_key=None, since_ts=None, startup_stale_before_ts=None, max_run_age_ts=None: 1,
    )
    with patch("app.main.get_account_store", return_value=mocked_store):
        with patch("app.main.create_scrape_run_recorder") as mocked_recorder:
            with patch("app.main.evaluate_search_start") as mocked_quota:
                response = client.get("/search/stream", params={"location": "Detroit, MI"})
    assert response.status_code == 429
    mocked_recorder.assert_not_called()
    mocked_quota.assert_not_called()
    assert "concurrency_blocked" in response.text
    assert "quota.concurrent_searches" in response.text


def test_search_stream_ignores_stale_startup_runs_for_concurrency_check() -> None:
    count_args: dict[str, object] = {}

    def count_running_scrape_runs(*, user_id=None, anon_key=None, since_ts=None, startup_stale_before_ts=None, max_run_age_ts=None) -> int:
        count_args["user_id"] = user_id
        count_args["anon_key"] = anon_key
        count_args["since_ts"] = since_ts
        count_args["startup_stale_before_ts"] = startup_stale_before_ts
        count_args["max_run_age_ts"] = max_run_age_ts
        return 0

    mocked_store = SimpleNamespace(
        get_scrape_run=lambda correlation_id, *, user_id=None, anon_key=None: None,
        count_running_scrape_runs=count_running_scrape_runs,
        anon_increment=lambda anon_key: 1,
        add_scrape_event=lambda **kwargs: None,
        create_scrape_run=lambda **kwargs: "run-1",
        finalize_scrape_run=lambda *args, **kwargs: None,
    )
    with patch("app.main.get_account_store", return_value=mocked_store):
        with patch(
            "app.main.evaluate_search_start",
            return_value=SearchQuotaDecision(True, False, None),
        ):
            with patch(
                "app.services.orchestrator.find_car_dealerships",
                new_callable=AsyncMock,
                return_value=[],
            ):
                with client.stream("GET", "/search/stream", params={"location": "Detroit, MI"}) as response:
                    assert response.status_code == 200
                    body = b"".join(response.iter_bytes())
    assert b"event: done" in body
    assert count_args["startup_stale_before_ts"] is not None
    assert count_args["max_run_age_ts"] is not None


def test_search_stream_quota_blocked_sse_includes_structured_error() -> None:
    mocked_store = SimpleNamespace(
        get_scrape_run=lambda correlation_id, *, user_id=None, anon_key=None: None,
        count_running_scrape_runs=lambda *, user_id=None, anon_key=None, since_ts=None, startup_stale_before_ts=None, max_run_age_ts=None: 0,
        add_scrape_event=lambda **kwargs: None,
        create_scrape_run=lambda **kwargs: "run-1",
        finalize_scrape_run=lambda *args, **kwargs: None,
    )
    with patch("app.main.get_account_store", return_value=mocked_store):
        with patch(
            "app.main.evaluate_search_start",
            return_value=SearchQuotaDecision(
                False,
                False,
                SearchErrorInfo(
                    code="quota.monthly_limit_free",
                    message="Monthly free search limit reached.",
                    phase="quota",
                    status="quota_blocked",
                    upgrade_required=True,
                    upgrade_tier="standard",
                ),
            ),
        ):
            with client.stream("GET", "/search/stream", params={"location": "Detroit, MI"}) as response:
                assert response.status_code == 200
                body = b"".join(response.iter_bytes())
    assert b"quota.monthly_limit_free" in body
    assert b"upgrade_required" in body


def test_search_logs_endpoint_returns_run_and_events() -> None:
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with client.stream("GET", "/search/stream", params={"location": "Detroit, MI"}) as r:
            assert r.status_code == 200
            _ = b"".join(r.iter_bytes())

    runs_response = client.get("/search/logs")
    assert runs_response.status_code == 200
    runs = runs_response.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["trigger_source"] == "interactive"
    assert runs[0]["status"] == "success"
    assert "places_metrics" in runs[0]

    detail_response = client.get(f"/search/logs/{runs[0]['correlation_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run"]["correlation_id"] == runs[0]["correlation_id"]
    assert "places_metrics" in detail["run"]
    assert any(event["event_type"] == "search_started" for event in detail["events"])
    assert any(event["event_type"] == "search_finished" for event in detail["events"])


def test_search_stop_endpoint_stops_owned_run() -> None:
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with client.stream("GET", "/search/stream", params={"location": "Detroit, MI"}) as r:
            assert r.status_code == 200
            _ = b"".join(r.iter_bytes())

    runs_response = client.get("/search/logs")
    correlation_id = runs_response.json()["runs"][0]["correlation_id"]

    with patch("app.main.cancel_active_search", return_value=True) as mock_cancel:
        response = client.post(f"/search/stop/{correlation_id}")

    assert response.status_code == 200
    assert response.json()["stopped"] is True
    mock_cancel.assert_called_once_with(correlation_id)


def test_admin_overview_requires_admin() -> None:
    local_client = TestClient(app)
    unauthorized = local_client.get("/admin/overview")
    assert unauthorized.status_code == 401


def test_admin_overview_allows_bootstrapped_admin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_emails", "matthew@zebarigroup.com")
    local_client = TestClient(app)
    signup = local_client.post("/auth/signup", json={"email": "matthew@zebarigroup.com", "password": "hunter22!!"})
    assert signup.status_code == 201

    response = local_client.get("/admin/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "stats" in payload
    assert payload["stats"]["total_users"] >= 1


def test_admin_user_update_appears_in_audit_and_detail(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_emails", "matthew@zebarigroup.com")
    local_client = TestClient(app)
    admin_signup = local_client.post("/auth/signup", json={"email": "matthew@zebarigroup.com", "password": "hunter22!!"})
    assert admin_signup.status_code == 201

    target_client = TestClient(app)
    target_signup = target_client.post("/auth/signup", json={"email": "customer@example.com", "password": "hunter22!!"})
    assert target_signup.status_code == 201
    target_user_id = target_signup.json()["id"]

    patch_response = local_client.patch(f"/admin/users/{target_user_id}", json={"tier": "premium", "is_admin": True})
    assert patch_response.status_code == 200
    assert patch_response.json()["user"]["tier"] == "premium"
    assert patch_response.json()["user"]["is_admin"] is True

    detail_response = local_client.get(f"/admin/users/{target_user_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["user"]["email"] == "customer@example.com"
    assert detail["user"]["tier"] == "premium"
    assert any(log["action"] == "user_updated" for log in detail["audit_logs"])

    audit_response = local_client.get("/admin/audit-log")
    assert audit_response.status_code == 200
    assert any(log["target_id"] == target_user_id for log in audit_response.json()["logs"])


def test_admin_can_reset_user_password(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_emails", "matthew@zebarigroup.com")
    admin_client = TestClient(app)
    admin_signup = admin_client.post("/auth/signup", json={"email": "matthew@zebarigroup.com", "password": "hunter22!!"})
    assert admin_signup.status_code == 201

    target_client = TestClient(app)
    target_signup = target_client.post("/auth/signup", json={"email": "customer@example.com", "password": "hunter22!!"})
    assert target_signup.status_code == 201
    target_user_id = target_signup.json()["id"]

    reset_response = admin_client.post(
        f"/admin/users/{target_user_id}/reset-password",
        json={"new_password": "new-secret-99"},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["ok"] is True

    login_response = target_client.post(
        "/auth/login",
        json={"email": "customer@example.com", "password": "new-secret-99"},
    )
    assert login_response.status_code == 200

    detail_response = admin_client.get(f"/admin/users/{target_user_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert any(log["action"] == "user_password_reset" for log in detail["audit_logs"])
