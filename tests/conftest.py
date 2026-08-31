"""Shared fixtures and mocks for EvalBench test suite."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from evalbench.api.main import app
from evalbench.api.deps import get_current_user
from evalbench.api import main as main_module
from evalbench.api import routes as routes_module
from evalbench.api import auth_routes as auth_routes_module
from evalbench.db import mongo as mongo_module


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


# ── Mock MongoDB ──
@pytest.fixture
def mock_db():
    """Patch all database references with an in-memory mock."""

    mock = MagicMock()

    # Suites collection
    mock.suites = MagicMock()
    mock.suites.insert_one = AsyncMock()
    mock.suites.find_one = AsyncMock()
    mock.suites.find = MagicMock()
    mock.suites.count_documents = AsyncMock(
        return_value=1
    )

    # Test runs collection
    mock.test_runs = MagicMock()
    mock.test_runs.insert_one = AsyncMock()
    mock.test_runs.find_one = AsyncMock()
    mock.test_runs.find = MagicMock()

    # Users collection
    mock.users = MagicMock()
    mock.users.find_one = AsyncMock()
    mock.users.insert_one = AsyncMock()
    mock.users.update_one = AsyncMock()
    mock.users.count_documents = AsyncMock(
        return_value=1
    )

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
            auth_routes_module,
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
