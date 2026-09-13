"""Suites and runs are scoped to the user who created them."""

from datetime import datetime, timezone

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user, owner_filter, owns
from evalbench.api.main import app

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"

ALICE = {"username": "alice", "role": "user", "_id": "a"}
BOB = {"username": "bob", "role": "user", "_id": "b"}
ADMIN = {"username": "root", "role": "admin", "_id": "r"}


@pytest.fixture
def as_alice(mock_db):
    """A client authenticated as a plain (non-admin) user."""
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestFilters:
    def test_admin_sees_everything(self):
        assert owner_filter(ADMIN) == {}

    def test_user_is_scoped_to_own(self):
        assert owner_filter(ALICE) == {"created_by": "alice"}

    def test_owns(self):
        assert owns({"created_by": "alice"}, ALICE) is True
        assert owns({"created_by": "bob"}, ALICE) is False
        # Legacy docs written before ownership have no owner.
        assert owns({}, ALICE) is False
        assert owns({}, ADMIN) is True


class TestSuiteScoping:
    def test_list_is_filtered_by_owner(self, as_alice, mock_db):
        async def empty():
            for _ in ():
                yield {}

        mock_db.suites.aggregate.return_value = empty()
        as_alice.get("/suites")
        pipeline = mock_db.suites.aggregate.call_args[0][0]
        assert pipeline[0] == {"$match": {"created_by": "alice"}}

    def test_cannot_read_another_users_suite(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID),
            "name": "Bob's",
            "created_by": "bob",
            "model": "m",
            "evaluator": "exact",
            "tests": [],
        }
        # 404, not 403 — don't confirm the id exists.
        assert as_alice.get(f"/suites/{SUITE_ID}").status_code == 404

    def test_can_read_own_suite(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID),
            "name": "Alice's",
            "created_by": "alice",
            "model": "m",
            "evaluator": "exact",
            "tests": [],
        }
        assert as_alice.get(f"/suites/{SUITE_ID}").status_code == 200

    def test_cannot_run_another_users_suite(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID),
            "created_by": "bob",
            "name": "x", "model": "m", "evaluator": "exact",
            "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
        }
        assert as_alice.post(f"/suites/{SUITE_ID}/run").status_code == 404

    def test_created_suite_records_the_owner(self, as_alice, mock_db):
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId(SUITE_ID)
        as_alice.post(
            "/suites/import",
            json={
                "name": "S", "model": "m", "evaluator": "exact",
                "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
            },
        )
        assert mock_db.suites.insert_one.call_args[0][0]["created_by"] == "alice"


class TestRunScoping:
    def test_cannot_read_another_users_run(self, as_alice, mock_db):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "created_by": "bob",
            "results": [],
            "created_at": datetime.now(timezone.utc),
        }
        assert as_alice.get(f"/runs/{RUN_ID}").status_code == 404
        assert as_alice.get(f"/runs/{RUN_ID}/summary").status_code == 404
        assert as_alice.get(f"/runs/{RUN_ID}/status").status_code == 404

    def test_regression_requires_owning_both_runs(self, as_alice, mock_db):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "created_by": "bob",
            "model": "m", "evaluator": "e", "suite_id": "s",
            "results": [],
            "created_at": datetime.now(timezone.utc),
        }
        r = as_alice.post(
            "/regression",
            json={"baseline_run_id": RUN_ID, "current_run_id": RUN_ID},
        )
        assert r.status_code == 404

    def test_regression_history_is_filtered_by_owner(self, as_alice, mock_db):
        """Regression: this endpoint had no owner filter because nothing
        called it, so Phase B7's audit walked straight past it."""

        async def empty():
            for _ in ():
                yield {}

        find = mock_db.test_runs.find
        find.return_value.sort.return_value.limit.return_value = empty()
        as_alice.get(f"/suites/{SUITE_ID}/regression-history")
        assert find.call_args[0][0] == {
            "suite_id": SUITE_ID,
            "created_by": "alice",
        }

    def test_cannot_promote_another_users_run_as_baseline(
        self, as_alice, mock_db
    ):
        """Owning the suite is not enough; the run has to be yours too."""
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID),
            "created_by": "alice",
            "name": "S",
        }
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "created_by": "bob",
            "status": "completed",
            "results": [],
            "created_at": datetime.now(timezone.utc),
        }
        r = as_alice.post(
            f"/suites/{SUITE_ID}/baseline", json={"run_id": RUN_ID}
        )
        assert r.status_code == 404
        mock_db.suites.update_one.assert_not_called()
