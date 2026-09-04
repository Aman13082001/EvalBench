"""Public playground endpoint: no auth, BYO key, caps, ephemeral."""

from unittest.mock import AsyncMock, patch

from bson import ObjectId

RUN_ID = "507f1f77bcf86cd799439011"

MOCK_SUITE = {
    "name": "Playground",
    "provider": "mock",
    "model": "mock-model",
    "evaluator": "icontains",
    "tests": [
        {"name": "t1", "prompt": "hi", "expected": "mock"},
        {"name": "t2", "prompt": "hi", "expected": "nope"},
    ],
}


class TestPlaygroundRun:
    def test_runs_without_auth_and_returns_summary(self, client, mock_db):
        mock_db.playground_runs.insert_one.return_value.inserted_id = ObjectId(
            RUN_ID
        )
        resp = client.post(
            "/playground/run", json={"suite": MOCK_SUITE, "provider_key": ""}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["run_id"] == RUN_ID
        assert body["total_tests"] == 2
        assert body["passed"] == 1  # t2 expects "nope"
        assert "results" in body
        assert "pass_rate_ci" in body

    def test_rejects_too_many_tests(self, client, mock_db):
        big = {**MOCK_SUITE, "tests": [MOCK_SUITE["tests"][0]] * 20}
        resp = client.post("/playground/run", json={"suite": big})
        assert resp.status_code == 400
        assert "capped at 12" in resp.json()["detail"]

    def test_rejects_hosted_provider_without_key(self, client, mock_db):
        hosted = {**MOCK_SUITE, "provider": "groq", "model": "x"}
        resp = client.post("/playground/run", json={"suite": hosted})
        assert resp.status_code == 400
        assert "needs a key" in resp.json()["detail"]

    def test_rejects_ollama(self, client, mock_db):
        local = {**MOCK_SUITE, "provider": "ollama", "model": "llama3.1"}
        resp = client.post("/playground/run", json={"suite": local})
        assert resp.status_code == 400
        assert "local Ollama" in resp.json()["detail"]

    def test_invalid_suite_400(self, client, mock_db):
        resp = client.post("/playground/run", json={"suite": {"name": "x"}})
        assert resp.status_code == 400


class TestPlaygroundGet:
    def test_permalink_fetch(self, client, mock_db):
        mock_db.playground_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "model": "mock-model",
            "evaluator": "icontains",
            "results": [
                {
                    "test_name": "t1", "prompt": "p", "expected": "",
                    "actual": "a", "latency_ms": 1, "tokens": 1,
                    "score": 1.0, "passed": True, "runs": 1,
                },
            ],
        }
        resp = client.get(f"/playground/runs/{RUN_ID}")
        assert resp.status_code == 200
        assert resp.json()["passed"] == 1

    def test_missing_permalink_404(self, client, mock_db):
        mock_db.playground_runs.find_one.return_value = None
        resp = client.get(f"/playground/runs/{RUN_ID}")
        assert resp.status_code == 404

    def test_providers_list_excludes_local(self, client, mock_db):
        resp = client.get("/playground/providers")
        body = resp.json()
        assert "ollama" not in body["providers"]
        assert "mock" not in body["providers"]
        assert "groq" in body["providers"]
        assert body["max_tests"] == 12


def test_run_uses_byo_key(client, mock_db):
    """The BYO key is passed to the runner, never persisted."""
    mock_db.playground_runs.insert_one.return_value.inserted_id = ObjectId(
        RUN_ID
    )
    hosted = {**MOCK_SUITE, "provider": "groq", "model": "x"}

    with patch("evalbench.api.playground.TestRunner") as RunnerCls:
        inst = RunnerCls.return_value
        inst.run_suite = AsyncMock(
            return_value=type(
                "R", (), {"results": [], "model": "x", "evaluator": "icontains"}
            )()
        )
        inst.close = AsyncMock()
        resp = client.post(
            "/playground/run",
            json={"suite": hosted, "provider_key": "gsk_secret"},
        )

    assert resp.status_code == 201
    RunnerCls.assert_called_once_with(provider_key="gsk_secret")
    persisted = mock_db.playground_runs.insert_one.call_args[0][0]
    assert "gsk_secret" not in str(persisted)
