"""Every data endpoint requires a user; only probes are public."""

import pytest
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app

# Endpoints that must stay reachable without auth.
PUBLIC = {
    ("GET", "/health"),
    ("GET", "/live"),
    ("GET", "/ready"),
}

# (method, path, json_body) — every one must 401 without a user.
PROTECTED = [
    ("GET", "/suites", None),
    ("GET", "/suites/models", None),
    ("GET", "/suites/507f1f77bcf86cd799439011", None),
    ("GET", "/suites/507f1f77bcf86cd799439011/export", None),
    ("GET", "/suites/507f1f77bcf86cd799439011/runs", None),
    ("GET", "/suites/507f1f77bcf86cd799439011/baseline", None),
    ("POST", "/suites/507f1f77bcf86cd799439011/run", None),
    ("POST", "/suites/507f1f77bcf86cd799439011/baseline", {"run_id": "x"}),
    ("GET", "/runs/507f1f77bcf86cd799439011", None),
    ("GET", "/runs/507f1f77bcf86cd799439011/summary", None),
    ("GET", "/runs/507f1f77bcf86cd799439011/status", None),
    ("POST", "/regression", {"baseline_run_id": "a", "current_run_id": "b"}),
]


@pytest.fixture
def unauthed_client(mock_db):
    """A client with the global auth override removed."""
    app.dependency_overrides.pop(get_current_user, None)
    with TestClient(app) as c:
        yield c
    # conftest re-registers the override at import time; restore it.
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_endpoint_requires_auth(unauthed_client, method, path, body):
    resp = unauthed_client.request(method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} should require auth"


@pytest.mark.parametrize("method,path", sorted(PUBLIC))
def test_probe_is_public(unauthed_client, method, path):
    resp = unauthed_client.request(method, path)
    assert resp.status_code != 401, f"{method} {path} should stay public"
