"""Integration tests for FastAPI endpoints (with mocked DB)."""

from datetime import datetime, timezone

from bson import ObjectId


class TestHealthEndpoint:
    def test_health_ok(self, client, mock_db):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestSuiteEndpoints:
    def test_create_suite(self, client, mock_db):
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId(
            "507f1f77bcf86cd799439011"
        )

        payload = {
            "name": "Test Suite",
            "model": "llama3.1",
            "evaluator": "exact",
            "tests": [
                {
                    "name": "t1",
                    "prompt": "p1",
                    "expected": "e1",
                    "threshold": 0.8,
                }
            ],
        }

        response = client.post("/suites", json=payload)

        assert response.status_code == 201
        assert "id" in response.json()

    def test_list_suites(self, client, mock_db):
        async def mock_cursor():
            yield {
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "name": "Suite 1",
                "model": "llama3.1",
                "evaluator": "exact",
                "tests": [],
                "created_at": datetime.now(timezone.utc),
            }

        mock_db.suites.aggregate.return_value = mock_cursor()

        response = client.get("/suites")

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_get_suite_not_found(self, client, mock_db):
        mock_db.suites.find_one.return_value = None

        response = client.get(
            "/suites/507f1f77bcf86cd799439011"
        )

        assert response.status_code == 404

    def test_export_suite(self, client, mock_db):
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "name": "Export Me",
            "model": "llama3.1",
            "evaluator": "exact",
            "tests": [
                {
                    "name": "t1",
                    "prompt": "p1",
                    "expected": "e1",
                    "threshold": 0.8,
                }
            ],
            "created_at": datetime.now(timezone.utc),
        }

        response = client.get(
            "/suites/507f1f77bcf86cd799439011/export"
        )

        assert response.status_code == 200
        assert "yaml" in response.json()


class TestRunEndpoints:
    def test_get_run_summary(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "suite_id": "suite_1",
            "model": "llama3.1",
            "evaluator": "exact",
            "results": [
                {
                    "test_name": "t1",
                    "prompt": "p1",
                    "expected": "e1",
                    "actual": "a1",
                    "latency_ms": 100.0,
                    "tokens": 10,
                    "score": 0.9,
                    "passed": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "created_at": datetime.now(timezone.utc),
        }

        response = client.get(
            "/runs/507f1f77bcf86cd799439011/summary"
        )

        assert response.status_code == 200

        data = response.json()

        assert data["total_tests"] == 1
        assert data["passed"] == 1
        assert data["pass_rate"] == 1.0

    def test_run_summary_excludes_errors_and_groups_by_category(
        self, client, mock_db
    ):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "suite_id": "suite_1",
            "model": "llama3.1",
            "evaluator": "semantic",
            "results": [
                {
                    "test_name": "m1", "prompt": "p", "expected": "e",
                    "actual": "a", "latency_ms": 100.0, "tokens": 10,
                    "score": 1.0, "passed": True, "category": "math",
                    "runs": 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "test_name": "m2", "prompt": "p", "expected": "e",
                    "actual": "", "latency_ms": 0.0, "tokens": 0,
                    "score": 0.0, "passed": False, "category": "math",
                    "runs": 0, "error": "Ollama timeout",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            ],
            "created_at": datetime.now(timezone.utc),
        }

        response = client.get(
            "/runs/507f1f77bcf86cd799439011/summary"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total_tests"] == 2
        assert data["errors"] == 1
        assert data["scored_tests"] == 1
        assert data["passed"] == 1
        assert data["pass_rate"] == 1.0  # errored test excluded
        assert data["by_category"]["math"]["total"] == 2
        assert data["by_category"]["math"]["errors"] == 1
        assert data["by_category"]["math"]["pass_rate"] == 1.0


class TestRegressionEndpoint:
    def test_regression_comparison(self, client, mock_db):
        run_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "suite_id": "suite_1",
            "model": "llama3.1",
            "evaluator": "exact",
            "results": [
                {
                    "test_name": "t1",
                    "prompt": "p1",
                    "expected": "e1",
                    "actual": "a1",
                    "latency_ms": 100.0,
                    "tokens": 10,
                    "score": 0.9,
                    "passed": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "created_at": datetime.now(timezone.utc),
        }

        mock_db.test_runs.find_one.return_value = run_doc

        payload = {
            "baseline_run_id": "507f1f77bcf86cd799439011",
            "current_run_id": "507f1f77bcf86cd799439011",
        }

        response = client.post(
            "/regression",
            json=payload,
        )

        assert response.status_code == 200

        data = response.json()

        assert "regression_detected" in data


class TestSummaryDoesNotBlameTheModelForTheProvider:
    """A run where a category got no answers at all, and where timeouts
    dominated the latencies. Found on a real run: 35 of 51 tests were
    rate-limited, and the page reported reasoning as 0.0% and average
    latency as 16.7s — the provider's bad day, presented as the model's."""

    def _doc(self):
        ok = lambda name, cat, ms: {  # noqa: E731
            "test_name": name, "prompt": "p", "expected": "e", "actual": "a",
            "latency_ms": ms, "tokens": 10, "score": 1.0, "passed": True,
            "category": cat, "runs": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        err = lambda name, cat: {  # noqa: E731
            "test_name": name, "prompt": "p", "expected": "e", "actual": "",
            "latency_ms": 20000.0, "tokens": 0, "score": 0.0, "passed": False,
            "category": cat, "runs": 0, "error": "rate limited",
            "rate_limited": 3,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "suite_id": "s", "model": "m", "evaluator": "exact",
            "created_at": datetime.now(timezone.utc),
            "results": [
                ok("a1", "arithmetic", 300.0),
                ok("a2", "arithmetic", 500.0),
                err("r1", "reasoning"),
                err("r2", "reasoning"),
            ],
        }

    def test_category_with_no_answers_has_no_reading_not_zero(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = self._doc()
        cat = client.get("/runs/507f1f77bcf86cd799439011/summary").json()["by_category"]
        assert cat["reasoning"]["errors"] == 2
        assert cat["reasoning"]["scored"] == 0
        assert cat["reasoning"]["pass_rate"] is None, "0% would mean the model failed them"
        assert cat["reasoning"]["avg_score"] is None
        assert cat["arithmetic"]["pass_rate"] == 1.0

    def test_latency_averages_only_tests_that_answered(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = self._doc()
        data = client.get("/runs/507f1f77bcf86cd799439011/summary").json()
        # (300 + 500) / 2, not (300 + 500 + 20000 + 20000) / 4
        assert data["avg_latency_ms"] == 400.0
