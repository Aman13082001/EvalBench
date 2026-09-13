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
    ("GET", "/runs/507f1f77bcf86cd799439011/export", None),
    ("GET", "/suites/507f1f77bcf86cd799439011/regression-history", None),
    ("POST", "/regression", {"baseline_run_id": "a", "current_run_id": "b"}),
    # workspace
    ("GET", "/runs", None),
    ("GET", "/suites/quota", None),
    ("GET", "/suites/bundled", None),
    ("POST", "/suites/bundled/safety/adopt", None),
]

# Routes that are public by design and not probes: auth itself, the
# metrics scrape, and the API docs. Each needs a reason to be here.
PUBLIC_BY_DESIGN = {
    "/metrics",           # Prometheus scrape target
    "/auth/login",        # you cannot be logged in to log in
    "/auth/register",
    "/docs", "/redoc", "/openapi.json",
    "/docs/oauth2-redirect",
}


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


def test_every_route_is_accounted_for():
    """The lists above are hand-written, which is fine until someone adds
    a route and forgets. This walks the real router and fails on any path
    that is neither listed as protected, nor listed as public with a
    reason. It is the difference between "every route requires auth" as a
    claim and as a fact."""
    from fastapi.routing import APIRoute

    def _template(p: str) -> str:
        # normalise concrete ids in PROTECTED back to templates
        return p.replace("507f1f77bcf86cd799439011", "{id}").replace("safety", "{slug}")

    protected = {
        (m, _template(p).replace("{id}", "{x}").replace("{slug}", "{x}"))
        for m, p, _ in PROTECTED
    }
    public = {p for _, p in PUBLIC} | PUBLIC_BY_DESIGN

    unaccounted = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        if r.path in public or r.path.startswith("/admin"):
            # /admin/* is covered by its own admin-gate tests
            continue
        norm = r.path
        for name in ("run_id", "suite_id", "slug", "username"):
            norm = norm.replace("{" + name + "}", "{x}")
        for m in r.methods or ():
            if (m, norm) not in protected:
                unaccounted.append(f"{m} {r.path}")

    assert not unaccounted, (
        "routes with no auth expectation recorded — add each to PROTECTED, "
        f"or to PUBLIC_BY_DESIGN with a reason: {sorted(unaccounted)}"
    )
