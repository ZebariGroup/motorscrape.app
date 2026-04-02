from __future__ import annotations

from app.config import settings
from app.db.account_store import get_account_store
from app.main import app
from fastapi.testclient import TestClient


def _signup(client: TestClient, email: str = "saved@example.com") -> str:
    response = client.post("/auth/signup", json={"email": email, "password": "hunter22!!"})
    assert response.status_code == 201
    return response.json()["id"]


def test_paid_user_can_crud_saved_searches() -> None:
    client = TestClient(app)
    user_id = _signup(client)
    store = get_account_store(settings.accounts_db_path)
    store.set_tier(user_id, "standard")

    create = client.post(
        "/saved-searches",
        json={
            "name": "Seattle BMW watchlist",
            "criteria": {
                "location": "Seattle, WA",
                "make": "BMW",
                "model": "X5",
                "vehicle_category": "car",
                "vehicle_condition": "used",
                "radius_miles": 30,
                "inventory_scope": "exclude_shared",
                "max_dealerships": 10,
                "max_pages_per_dealer": 4,
                "market_region": "us",
            },
        },
    )
    assert create.status_code == 201
    saved_search = create.json()["saved_search"]
    assert saved_search["criteria"]["model"] == "X5"

    listed = client.get("/saved-searches")
    assert listed.status_code == 200
    assert len(listed.json()["saved_searches"]) == 1

    update = client.patch(
        f"/saved-searches/{saved_search['id']}",
        json={
            "name": "Seattle BMW SUV watchlist",
            "criteria": {
                "location": "Seattle, WA",
                "make": "BMW",
                "model": "X3,X5",
                "vehicle_category": "car",
                "vehicle_condition": "used",
                "radius_miles": 50,
                "inventory_scope": "all",
                "max_dealerships": 10,
                "max_pages_per_dealer": 4,
                "market_region": "eu",
            },
        },
    )
    assert update.status_code == 200
    updated = update.json()["saved_search"]
    assert updated["name"] == "Seattle BMW SUV watchlist"
    assert updated["criteria"]["market_region"] == "eu"

    removed = client.delete(f"/saved-searches/{saved_search['id']}")
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    assert client.get("/saved-searches").json()["saved_searches"] == []


def test_free_user_cannot_create_saved_searches() -> None:
    client = TestClient(app)
    _signup(client, email="free-saved@example.com")

    create = client.post(
        "/saved-searches",
        json={
            "name": "Blocked free plan search",
            "criteria": {
                "location": "Portland, OR",
                "make": "Toyota",
                "model": "Tacoma",
                "vehicle_category": "car",
                "vehicle_condition": "used",
                "radius_miles": 25,
                "inventory_scope": "all",
                "max_dealerships": 8,
                "max_pages_per_dealer": 3,
                "market_region": "us",
            },
        },
    )
    assert create.status_code == 403
    assert "Saved searches are available" in create.json()["detail"]
