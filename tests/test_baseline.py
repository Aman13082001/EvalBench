"""Baseline promotion endpoints."""

from bson import ObjectId

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"


class TestSetBaseline:
    def test_promote_completed_run(self, client, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID), "name": "S", "model": "m",
            "evaluator": "exact", "tests": [],
        }
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID), "status": "completed",
        }

        resp = client.post(
            f"/suites/{SUITE_ID}/baseline", json={"run_id": RUN_ID}
        )
        assert resp.status_code == 200
        assert resp.json()["baseline_run_id"] == RUN_ID

        _flt, update = mock_db.suites.update_one.call_args[0]
        assert update["$set"]["baseline_run_id"] == RUN_ID

    def test_reject_non_completed_run(self, client, mock_db):
        mock_db.suites.find_one.return_value = {"_id": ObjectId(SUITE_ID)}
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID), "status": "running",
        }
        resp = client.post(
            f"/suites/{SUITE_ID}/baseline", json={"run_id": RUN_ID}
        )
        assert resp.status_code == 400
        assert "completed" in resp.json()["detail"]

    def test_missing_run_id(self, client, mock_db):
        resp = client.post(f"/suites/{SUITE_ID}/baseline", json={})
        assert resp.status_code == 400

    def test_run_not_found(self, client, mock_db):
        mock_db.suites.find_one.return_value = {"_id": ObjectId(SUITE_ID)}
        mock_db.test_runs.find_one.return_value = None
        resp = client.post(
            f"/suites/{SUITE_ID}/baseline", json={"run_id": RUN_ID}
        )
        assert resp.status_code == 404


class TestGetBaseline:
    def test_returns_current_baseline(self, client, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID), "baseline_run_id": RUN_ID,
        }
        resp = client.get(f"/suites/{SUITE_ID}/baseline")
        assert resp.status_code == 200
        assert resp.json()["baseline_run_id"] == RUN_ID

    def test_none_when_unset(self, client, mock_db):
        mock_db.suites.find_one.return_value = {"_id": ObjectId(SUITE_ID)}
        resp = client.get(f"/suites/{SUITE_ID}/baseline")
        assert resp.json()["baseline_run_id"] is None
