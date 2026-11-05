import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY = {"X-Internal-Key": "test-key"}


@pytest.fixture()
def client():
    return TestClient(create_app(Settings(internal_api_key="test-key")))


def test_health_is_open(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_internal_routes_need_the_key(client):
    body = {"skill": "powers", "target_rating": 1200}
    assert client.post("/internal/problems", json=body).status_code == 401
    assert client.post("/internal/problems", json=body, headers={"X-Internal-Key": "nope"}).status_code == 401
    assert client.get("/internal/daily/2026-10-28").status_code == 401


@pytest.mark.parametrize("skill", ["multiplication", "percentages", "fractions", "powers"])
def test_generate_returns_a_consistent_problem(client, skill):
    r = client.post("/internal/problems", json={"skill": skill, "target_rating": 1200}, headers=KEY)
    assert r.status_code == 200
    p = r.json()
    assert p["skill"] == skill
    bigger = "left" if p["left"]["value"] > p["right"]["value"] else "right"
    assert p["answer"] == bigger
    assert abs(p["rating"] - 1200) < 150


def test_generate_rejects_bad_input(client):
    assert client.post("/internal/problems", json={"skill": "calculus", "target_rating": 1200}, headers=KEY).status_code == 422
    assert client.post("/internal/problems", json={"skill": "powers", "target_rating": -5}, headers=KEY).status_code == 422


def test_daily_set_is_deterministic_and_has_ten(client):
    a = client.get("/internal/daily/2026-10-28", headers=KEY).json()
    b = client.get("/internal/daily/2026-10-28", headers=KEY).json()
    c = client.get("/internal/daily/2026-10-29", headers=KEY).json()
    assert a == b
    assert len(a["problems"]) == 10
    assert [p["id"] for p in a["problems"]] != [p["id"] for p in c["problems"]]


def test_daily_rejects_non_dates(client):
    assert client.get("/internal/daily/not-a-date", headers=KEY).status_code == 422
    assert client.get("/internal/daily/2026-13-45", headers=KEY).status_code == 422
