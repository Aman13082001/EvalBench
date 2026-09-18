"""Don't offer a provider the server cannot actually reach.

The model picker listed six providers. Exactly one — Groq — had a key on
this server; the other four hosted ones had none. Choosing GitHub Models
with "use EvalBench's key" passed validation, queued a run, and then
failed inside the worker with "Provider 'github' needs an API key". The
user saw a failed run rather than a reason.

Two fixes, because they answer different questions. `configured_providers`
lets the UI stop offering what cannot work, and the run endpoint refuses
it at submission with a message that says what to do instead — the API
has to hold that line regardless of what any client shows.
"""

from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.core.providers import configured_providers

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"
ALICE = {"username": "alice", "role": "user", "_id": "a"}

SUITE_DOC = {
    "_id": ObjectId(SUITE_ID), "name": "S", "provider": "groq",
    "model": "openai/gpt-oss-20b", "evaluator": "exact", "created_by": "alice",
    "samples": 1, "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
}


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestWhatTheServerCanReach:
    def test_a_provider_with_a_key_is_configured(self):
        with patch("evalbench.core.providers.settings") as s:
            s.groq_api_key = "gsk_real"
            s.gemini_api_key = ""
            s.github_token = ""
            s.openrouter_api_key = ""
            s.openai_api_key = ""
            got = configured_providers()
        assert "groq" in got
        assert "gemini" not in got
        assert "openai" not in got

    def test_providers_needing_no_key_are_always_available(self):
        """Ollama runs locally and the replay provider answers from a
        recording; neither has a key to be missing."""
        with patch("evalbench.core.providers.settings") as s:
            s.groq_api_key = ""
            s.gemini_api_key = ""
            s.github_token = ""
            s.openrouter_api_key = ""
            s.openai_api_key = ""
            got = configured_providers()
        assert "ollama" in got and "demo" in got

    def test_the_endpoint_says_which_need_your_own_key(self, as_alice):
        body = as_alice.get("/suites/providers").json()
        by_id = {p["id"]: p for p in body}
        assert by_id["ollama"]["needs_key"] is False
        # every hosted one is listed whether or not this server has a key,
        # because a caller can always bring their own
        assert set(by_id) >= {"groq", "gemini", "github", "openrouter", "openai"}
        assert all("server_key" in p and "label" in p for p in body)


class TestTheRunEndpointRefusesEarly:
    def test_server_key_run_on_an_unconfigured_provider_is_rejected(
        self, as_alice, mock_db
    ):
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        with patch(
            "evalbench.api.routes.configured_providers", return_value=["groq"]
        ):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run", json={"provider": "openai"}
            )
        assert r.status_code == 400
        detail = r.json()["detail"].lower()
        assert "openai" in detail and "own" in detail
        mock_db.test_runs.insert_one.assert_not_called()

    def test_the_same_provider_is_fine_with_your_own_key(
        self, as_alice, mock_db
    ):
        """The server's missing key is irrelevant when the caller supplies
        one — refusing then would be the API inventing a limit."""
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch(
            "evalbench.api.routes.configured_providers", return_value=["groq"]
        ), patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"provider": "openai", "provider_key": "sk-mine"},
            )
        assert r.status_code == 202, r.text

    def test_a_configured_provider_still_runs(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch(
            "evalbench.api.routes.configured_providers", return_value=["groq"]
        ), patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(f"/suites/{SUITE_ID}/run", json={"provider": "groq"})
        assert r.status_code == 202, r.text


class TestAKeyOnlyGoesWhereAKeyIsWanted:
    """A caller's key applies to hosted providers. A suite can still route
    its judge through a keyless one — the demo suite judges with the
    replay provider, and a suite might judge locally on Ollama — and
    handing those a key crashed the run with "unexpected keyword argument
    'api_key'". Found by running a bring-your-own-key job against the
    demo suite."""

    def test_keyless_providers_ignore_a_supplied_key(self):
        from evalbench.core.providers import get_provider

        for name in ("demo", "mock", "ollama"):
            p = get_provider(name, api_key="gsk_whatever")
            assert p is not None

    def test_hosted_providers_still_receive_it(self):
        from evalbench.core.providers import get_provider

        p = get_provider("groq", api_key="gsk_mine")
        assert p._client.headers["Authorization"] == "Bearer gsk_mine"

    @pytest.mark.asyncio
    async def test_the_runner_survives_a_keyless_judge(self):
        """The whole path, not just the factory: a key on the run, a
        judge on a provider that takes none."""
        from evalbench.core.runner import TestRunner

        r = TestRunner(provider_key="gsk_mine")
        judge = r._make_provider("demo")
        assert judge is not None
        await r.close()
