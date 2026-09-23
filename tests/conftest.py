"""Shared fixtures and mocks for EvalBench test suite."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# The API refuses to start with placeholder secrets unless this is set.
os.environ.setdefault("EVALBENCH_ALLOW_INSECURE", "1")

from evalbench import jobs as jobs_module  # noqa: E402
from evalbench.api import admin as admin_module  # noqa: E402
from evalbench.api import auth_routes as auth_routes_module  # noqa: E402
from evalbench.api import dashboard as dashboard_module  # noqa: E402
from evalbench.api import deps as deps_module  # noqa: E402
from evalbench.api import main as main_module  # noqa: E402
from evalbench.api import routes as routes_module  # noqa: E402
from evalbench.api.deps import get_current_user, limiter  # noqa: E402
from evalbench.api.main import app  # noqa: E402
from evalbench.db import mongo as mongo_module  # noqa: E402

# Rate limiting is not what unit tests should exercise.
limiter.enabled = False


# ── Override auth for all route tests ──
async def override_get_current_user():
    return {
        "username": "testuser",
        "role": "admin",
        "_id": "507f1f77bcf86cd799439011",
    }


app.dependency_overrides[get_current_user] = (
    override_get_current_user
)


# ── What this instance is configured for ──
@pytest.fixture(autouse=True)
def instance_has_a_hosted_key(monkeypatch):
    """State the server's credentials instead of inheriting them.

    `configured_providers()` reads the process's environment, so the
    suite quietly asked the machine it ran on. A developer with
    GROQ_API_KEY in `.env` ran one test suite and CI, which has no
    `.env`, ran another: ten run-endpoint tests passed locally and
    failed there with 400 "this instance has no key for 'groq'" — a
    red build that no local run could reproduce.

    Every test now runs against an instance that has one hosted key, a
    placeholder that never leaves the process. The tests that are about
    configuration clear or patch it themselves, and still do.
    """
    monkeypatch.setattr(
        "evalbench.core.providers.settings.groq_api_key", "gsk_test_placeholder",
        raising=False,
    )
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_placeholder")


# ── Is there a local model here? ──
@pytest.fixture(autouse=True)
def instance_has_a_local_model():
    """State it, the way the hosted key above is stated.

    `/providers` and the run gate ask whether an Ollama answers. On a
    developer's machine one usually does; on CI none ever will. Two
    tests about entirely different things — which providers need your
    own key, and that local runs are not capped — passed here and failed
    there for that reason alone.

    So every test runs against an instance that has one. The tests that
    are *about* the probe patch it themselves, both ways.
    """
    with patch.object(routes_module, "local_models_available", return_value=True):
        yield


# ── Mock MongoDB ──
@pytest.fixture
def mock_db():
    """Patch all database references with an in-memory mock."""

    mock = MagicMock()

    # Suites collection
    mock.suites = MagicMock()
    mock.suites.insert_one = AsyncMock()
    mock.suites.find_one = AsyncMock(return_value=None)
    mock.suites.update_one = AsyncMock()
    mock.suites.find = MagicMock()
    mock.suites.aggregate = MagicMock()
    mock.suites.count_documents = AsyncMock(
        return_value=1
    )
    mock.suites.create_index = AsyncMock()

    # Test runs collection
    mock.test_runs = MagicMock()
    mock.test_runs.insert_one = AsyncMock()
    mock.test_runs.find_one = AsyncMock(return_value=None)
    mock.test_runs.update_one = AsyncMock()
    mock.test_runs.update_many = AsyncMock(
        return_value=MagicMock(modified_count=0)
    )
    mock.test_runs.find = MagicMock()
    mock.test_runs.create_index = AsyncMock()
    mock.test_runs.count_documents = AsyncMock(return_value=0)

    # Users collection
    mock.users = MagicMock()
    mock.users.find_one = AsyncMock()
    mock.users.insert_one = AsyncMock()
    mock.users.update_one = AsyncMock()
    mock.users.count_documents = AsyncMock(
        return_value=1
    )
    mock.users.create_index = AsyncMock()
    mock.users.drop_index = AsyncMock()
    mock.users.find = MagicMock()

    mock.command = AsyncMock(
        return_value={"ok": 1}
    )

    # Patch every module that imported db directly.
    with (
        patch.object(
            mongo_module,
            "db",
            mock
        ),
        patch.object(
            main_module,
            "db",
            mock
        ),
        patch.object(
            routes_module,
            "db",
            mock
        ),
        patch.object(
            jobs_module,
            "db",
            mock
        ),
        patch.object(
            admin_module,
            "db",
            mock
        ),
        patch.object(
            auth_routes_module,
            "db",
            mock
        ),
        # Auth itself: the key and token lookups. Unpatched, every test
        # that sent a key was querying the real database on 27017.
        patch.object(
            deps_module,
            "db",
            mock
        ),
        patch.object(
            dashboard_module,
            "db",
            mock
        ),
    ):
        yield mock


# ── FastAPI TestClient ──
@pytest.fixture
def client(mock_db):
    """Create FastAPI test client after MongoDB is patched."""

    with TestClient(app) as c:
        yield c


# ── Mock Ollama responses ──
@pytest.fixture
def mock_ollama_response():
    return {
        "response": "This is a test response.",
        "total_duration": 1_500_000_000,
        "eval_count": 42,
    }


@pytest.fixture
def mock_ollama_refusal():
    return {
        "response": "I cannot help with that request.",
        "total_duration": 800_000_000,
        "eval_count": 12,
    }
