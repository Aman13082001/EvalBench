"""End-to-end through the real API + a real async Mongo (mongomock-motor)
+ the in-process `mock` provider. No network, no Docker, but every layer
is exercised: auth, suite CRUD, the async job, the runner, aggregation,
baseline promotion, regression.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from evalbench import jobs as jobs_module
from evalbench.api import auth_routes as auth_routes_module
from evalbench.api import deps as deps_module
from evalbench.api import main as main_module
from evalbench.api import routes as routes_module
from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.db import mongo as mongo_module

SUITE = {
    "name": "Integration Suite",
    "provider": "mock",
    "model": "mock-model",
    "evaluator": "icontains",
    "samples": 1,
    "concurrency": 2,
    "tests": [
        {"name": "t1", "prompt": "say hi", "expected": "mock", "category": "a"},
        {"name": "t2", "prompt": "say hi", "expected": "mock", "category": "a"},
        {"name": "t3", "prompt": "say hi", "expected": "mock", "category": "b"},
        {"name": "t4", "prompt": "say hi", "expected": "nope", "category": "b"},
    ],
}


@pytest.fixture(scope="module")
def live_client():
    """One real API + one real async Mongo, shared by this module's tests.

    Module-scoped so mongomock-motor keeps a single event loop; tests use
    distinct usernames/suites to stay independent.
    """
    mock_client = AsyncMongoMockClient()
    real_db = mock_client["evalbench_it"]
    dummy_client = MagicMock()  # lifespan shutdown calls client.close()

    app.dependency_overrides.pop(get_current_user, None)

    with (
        patch.object(mongo_module, "db", real_db),
        patch.object(mongo_module, "client", dummy_client),
        patch.object(main_module, "db", real_db),
        patch.object(main_module, "client", dummy_client),
        patch.object(routes_module, "db", real_db),
        patch.object(jobs_module, "db", real_db),
        patch.object(auth_routes_module, "db", real_db),
        patch.object(deps_module, "db", real_db),
        TestClient(app) as client,
    ):
        yield client

    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


@pytest.mark.integration
def test_full_flow_register_run_baseline_regression(live_client):
    c = live_client

    # 1. register -> get an API key
    r = c.post("/auth/register", json={"username": "it", "password": "pw12345"})
    assert r.status_code in (200, 201), r.text
    key = r.json()["api_key"]
    h = {"X-API-Key": key}

    # 2. auth actually works (and is required)
    assert c.get("/suites").status_code == 401
    assert c.get("/suites", headers=h).status_code == 200

    # 3. import the suite
    r = c.post("/suites/import", json=SUITE, headers=h)
    assert r.status_code == 201, r.text
    suite_id = r.json()["id"]

    # 4. run it — 202, background task executes under TestClient
    r = c.post(f"/suites/{suite_id}/run", headers=h)
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    # 5. status is terminal, progress complete
    s = c.get(f"/runs/{run_id}/status", headers=h).json()
    assert s["status"] == "completed"
    assert s["completed_tests"] == 4

    # 6. summary: 3/4 pass (t4 expects "nope"), category + assertion rollups
    summary = c.get(f"/runs/{run_id}/summary", headers=h).json()
    assert summary["total_tests"] == 4
    assert summary["passed"] == 3
    assert summary["pass_rate"] == 0.75
    assert summary["by_category"]["a"]["pass_rate"] == 1.0
    assert summary["assertion_types"]["icontains"]["passed"] == 3

    # 7. promote this run as the baseline
    r = c.post(
        f"/suites/{suite_id}/baseline", json={"run_id": run_id}, headers=h
    )
    assert r.status_code == 200
    assert (
        c.get(f"/suites/{suite_id}/baseline", headers=h).json()[
            "baseline_run_id"
        ]
        == run_id
    )

    # 8. second run, then regression check against the baseline
    run2 = c.post(f"/suites/{suite_id}/run", headers=h).json()["run_id"]
    r = c.post(
        "/regression",
        json={"baseline_run_id": run_id, "current_run_id": run2},
        headers=h,
    )
    assert r.status_code == 200
    comp = r.json()
    # deterministic mock -> identical runs -> no regression
    assert comp["regression_detected"] is False
    assert len(comp["per_test"]) == 4
    assert all(t["delta"] == 0.0 for t in comp["per_test"])


@pytest.mark.integration
def test_users_cannot_see_each_others_suites(live_client):
    """Ownership isolation, proven against a real database."""
    c = live_client

    a = c.post(
        "/auth/register", json={"username": "owner_a", "password": "pw12345"}
    ).json()["api_key"]
    b = c.post(
        "/auth/register", json={"username": "owner_b", "password": "pw12345"}
    ).json()["api_key"]
    ha, hb = {"X-API-Key": a}, {"X-API-Key": b}

    suite_a = c.post("/suites/import", json=SUITE, headers=ha).json()["id"]

    # A sees it; B does not, and gets 404 rather than 403.
    assert c.get(f"/suites/{suite_a}", headers=ha).status_code == 200
    assert c.get(f"/suites/{suite_a}", headers=hb).status_code == 404
    assert c.post(f"/suites/{suite_a}/run", headers=hb).status_code == 404

    names_b = [s["name"] for s in c.get("/suites", headers=hb).json()]
    assert SUITE["name"] not in names_b

    # A's run is invisible to B too.
    run_a = c.post(f"/suites/{suite_a}/run", headers=ha).json()["run_id"]
    assert c.get(f"/runs/{run_a}/summary", headers=ha).status_code == 200
    assert c.get(f"/runs/{run_a}/summary", headers=hb).status_code == 404


@pytest.mark.integration
def test_run_persists_and_lists(live_client):
    c = live_client
    key = c.post(
        "/auth/register", json={"username": "it2", "password": "pw12345"}
    ).json()["api_key"]
    h = {"X-API-Key": key}

    suite_id = c.post("/suites/import", json=SUITE, headers=h).json()["id"]
    c.post(f"/suites/{suite_id}/run", headers=h)
    c.post(f"/suites/{suite_id}/run", headers=h)

    runs = c.get(f"/suites/{suite_id}/runs", headers=h).json()
    assert len(runs) == 2
    assert all(run["status"] == "completed" for run in runs)
