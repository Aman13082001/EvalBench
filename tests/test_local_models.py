"""Do not offer a local model an instance cannot reach.

The picker once hard-coded five hosted providers when only one had a
key, and the failure surfaced as a dead run minutes later. That was
fixed for keyed providers. Ollama slipped through the same hole from the
other side: it needs no key, so it is always offered — including on a
hosted instance where no Ollama exists and nothing will ever answer.

Same bug, same cost to the visitor: pick the obvious free option, wait,
get a connection error.
"""

import pathlib
from unittest.mock import patch

import pytest
import yaml

from evalbench.api import routes
from evalbench.benchmarks import BUNDLED

SUITES = pathlib.Path(__file__).resolve().parents[1] / "suites"


class TestTheProviderListReflectsReality:
    @pytest.mark.asyncio
    async def test_ollama_is_offered_when_it_answers(self, mock_db):
        with patch.object(routes, "local_models_available", return_value=True):
            names = {p["id"] for p in await routes.list_providers(user={"username": "a"})}
        assert "ollama" in names

    @pytest.mark.asyncio
    async def test_ollama_is_not_offered_when_nothing_answers(self, mock_db):
        """A hosted instance has no Ollama. Offering it is offering a
        dead end."""
        with patch.object(routes, "local_models_available", return_value=False):
            names = {p["id"] for p in await routes.list_providers(user={"username": "a"})}
        assert "ollama" not in names

    @pytest.mark.asyncio
    async def test_the_hosted_ones_are_untouched_either_way(self, mock_db):
        with patch.object(routes, "local_models_available", return_value=False):
            names = {p["id"] for p in await routes.list_providers(user={"username": "a"})}
        assert {"groq", "custom", "demo"} <= names


class TestBundledBenchmarksNameTheirProvider:
    """`TestSuite.provider` defaults to "ollama" — correct when this was
    an Ollama-only tool, a trap now. A bundled benchmark that leaves it
    out aims at a local model that a hosted instance does not have, and
    only the web form's own fallback hides it."""

    @pytest.mark.parametrize("entry", BUNDLED, ids=lambda b: b["slug"])
    def test_every_bundled_suite_says_which_provider(self, entry):
        data = yaml.safe_load((SUITES / entry["file"]).read_text(encoding="utf-8"))
        assert data.get("provider"), (
            f"{entry['file']} relies on the schema default (ollama)"
        )

    @pytest.mark.parametrize("entry", BUNDLED, ids=lambda b: b["slug"])
    def test_none_of_them_need_a_local_model(self, entry):
        """Whatever a bundled benchmark names must be runnable on an
        instance with no GPU and no Ollama."""
        data = yaml.safe_load((SUITES / entry["file"]).read_text(encoding="utf-8"))
        assert data.get("provider") != "ollama", f"{entry['file']} needs a local model"


class TestARunCannotAimAtAModelThatIsNotThere:
    """Dropping it from the picker is not enough. The API still took the
    run, queued it, and let it die inside the worker on a connection
    error — a failed evaluation where a refusal with a reason belongs."""

    def test_an_ollama_run_is_refused_when_nothing_answers(self, mock_db):
        from bson import ObjectId
        from fastapi.testclient import TestClient

        from evalbench.api.deps import get_current_user
        from evalbench.api.main import app

        suite_id = "507f1f77bcf86cd799439011"
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(suite_id), "name": "S", "provider": "groq",
            "model": "openai/gpt-oss-20b", "evaluator": "exact",
            "created_by": "alice",
            "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
        }
        app.dependency_overrides[get_current_user] = lambda: {
            "username": "alice", "role": "user", "_id": "a"
        }
        try:
            with (
                patch.object(routes, "local_models_available", return_value=False),
                patch.object(routes, "submit_run"),
                TestClient(app) as c,
            ):
                r = c.post(f"/suites/{suite_id}/run", json={"provider": "ollama"})
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert r.status_code == 400, r.text
        assert "local model" in r.json()["detail"].lower()
        mock_db.test_runs.insert_one.assert_not_called()
