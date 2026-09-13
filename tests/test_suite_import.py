"""Importing a suite is create-or-update by name, not create.

`evalbench run suite.yaml` imports the suite before every run. When that
was a plain insert, every CLI run left a new copy behind: one database
reached 70 suites with 18 distinct names, run history was scattered
across the copies, and a baseline set on one copy meant nothing to the
next. A benchmark's identity is its name within an account; importing
the same name again updates that benchmark in place and keeps its id,
its runs and its baseline.
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app

SUITE_ID = "507f1f77bcf86cd799439011"
ALICE = {"username": "alice", "role": "user", "_id": "a"}

PAYLOAD = {
    "name": "Safety",
    "provider": "groq",
    "model": "openai/gpt-oss-20b",
    "evaluator": "exact",
    "description": "Refusal and over-refusal.",
    "tests": [{"name": "t1", "prompt": "p", "expected": "e"}],
}


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestImportIsAnUpsert:
    def test_new_name_is_created(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = None
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId(SUITE_ID)
        r = as_alice.post("/suites/import", json=PAYLOAD)
        assert r.status_code == 201, r.text
        assert r.json()["created"] is True
        assert r.json()["id"] == SUITE_ID
        doc = mock_db.suites.insert_one.call_args[0][0]
        assert doc["created_by"] == "alice"
        assert doc["description"] == "Refusal and over-refusal."

    def test_same_name_updates_in_place(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID),
            "name": "Safety",
            "created_by": "alice",
            "baseline_run_id": "run-1",
        }
        changed = {**PAYLOAD, "model": "openai/gpt-oss-120b",
                   "tests": PAYLOAD["tests"] * 2}
        r = as_alice.post("/suites/import", json=changed)
        assert r.status_code == 200, r.text
        assert r.json() == {"id": SUITE_ID, "created": False,
                            "message": "Suite updated"}
        mock_db.suites.insert_one.assert_not_called()
        # it looked for *this user's* suite of that name
        q = mock_db.suites.find_one.call_args[0][0]
        assert q == {"name": "Safety", "created_by": "alice"}
        # and rewrote the definition, keeping what makes it the same suite
        filt, update = mock_db.suites.update_one.call_args[0]
        assert filt == {"_id": ObjectId(SUITE_ID)}
        s = update["$set"]
        assert s["model"] == "openai/gpt-oss-120b"
        assert len(s["tests"]) == 2
        assert "updated_at" in s
        for kept in ("created_at", "created_by", "baseline_run_id", "bundled_slug"):
            assert kept not in s, f"{kept} must survive a re-import"

    def test_same_name_other_owner_is_a_different_suite(self, as_alice, mock_db):
        """Names are per account. Alice importing "Safety" must not touch
        Bob's "Safety" — and the lookup is what enforces that."""
        mock_db.suites.find_one.return_value = None
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId(SUITE_ID)
        as_alice.post("/suites/import", json=PAYLOAD)
        assert mock_db.suites.find_one.call_args[0][0]["created_by"] == "alice"

    def test_create_endpoint_upserts_too(self, as_alice, mock_db):
        """`POST /suites` and `POST /suites/import` are the same operation
        with a stricter body; they must not disagree about identity."""
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID), "name": "Safety", "created_by": "alice",
        }
        r = as_alice.post("/suites", json=PAYLOAD)
        assert r.status_code == 200
        assert r.json()["created"] is False
        mock_db.suites.insert_one.assert_not_called()


class TestListIsASummary:
    def test_list_omits_test_bodies_and_counts_them(self, as_alice, mock_db):
        """The list page once downloaded 129 KB — every prompt of every
        suite — to print "51 tests". A list row is name, description and
        a count; the definition loads when you open the benchmark."""
        async def gen():
            yield {
                "_id": ObjectId(SUITE_ID), "name": "Safety",
                "description": "Refusal and over-refusal.",
                "created_by": "alice", "test_count": 19,
            }

        chain = mock_db.suites.aggregate.return_value = gen()
        r = as_alice.get("/suites")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["test_count"] == 19
        assert row["description"] == "Refusal and over-refusal."
        assert "tests" not in row
        # the pipeline is what drops the bodies: count first, then exclude
        pipeline = mock_db.suites.aggregate.call_args[0][0]
        add = next(s["$addFields"] for s in pipeline if "$addFields" in s)
        assert add["test_count"] == {"$size": {"$ifNull": ["$tests", []]}}
        proj = next(s["$project"] for s in pipeline if "$project" in s)
        assert proj == {"tests": 0}
        assert chain is not None
