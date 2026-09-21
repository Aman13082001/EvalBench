"""The next pass from SECURITY.md's known-gaps table: the ones that
matter for a free-tier public demo, done.

- A password has a floor. `password: "a"` was accepted.
- A request body has a ceiling. A 200 MB `answers` upload cost memory
  before validation could refuse it.
- Sign out means signed out. A token worked until it expired — seven
  days — whatever the user did. Every account carries a token version;
  a token records the version it was minted under; sign-out and a
  password reset bump it, and every older token is refused on its next
  request. Bans already worked this way; now logout does too.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from evalbench.api import auth_routes, main
from evalbench.api.auth import create_access_token, get_password_hash
from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.cli import app as app_cli

ALICE = {"username": "alice", "role": "user", "_id": "a"}


@pytest.fixture
def anon(mock_db):
    saved = app.dependency_overrides.pop(get_current_user, None)
    with TestClient(app) as c:
        yield c
    if saved:
        app.dependency_overrides[get_current_user] = saved


class TestPasswordFloor:
    def test_seven_characters_is_refused_with_the_rule(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "new@example.com", "password": "1234567"})
        assert r.status_code == 422
        assert "8" in r.text
        mock_db.users.insert_one.assert_not_called()

    def test_eight_is_enough(self, anon, mock_db):
        """A floor, not a policy: the rest is the user's business."""
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "new@example.com", "password": "12345678"})
        assert r.status_code == 201


class TestBodyCeiling:
    def test_a_body_over_the_limit_is_refused_before_it_is_read(self, mock_db):
        app.dependency_overrides[get_current_user] = lambda: ALICE
        with patch.object(main.settings, "max_body_bytes", 1024), TestClient(app) as c:
            r = c.post(
                "/suites/507f1f77bcf86cd799439011/run",
                content=b'{"answers": "' + b"x" * 4096 + b'"}',
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 413
        assert "1 KB" in r.json()["detail"] or "1024" in r.json()["detail"]
        mock_db.suites.find_one.assert_not_called()

    def test_a_chunked_body_is_cut_off_at_the_limit_too(self, mock_db):
        """No Content-Length to check up front: the body is counted as
        it streams and refused the moment it passes the line."""
        app.dependency_overrides[get_current_user] = lambda: ALICE

        def chunks():
            for _ in range(8):
                yield b"x" * 1024

        with patch.object(main.settings, "max_body_bytes", 2048), TestClient(app) as c:
            r = c.post(
                "/suites/import",
                content=chunks(),
                headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
            )
        assert r.status_code == 413

    def test_a_normal_body_is_untouched(self, mock_db):
        app.dependency_overrides[get_current_user] = lambda: ALICE
        with patch.object(main.settings, "max_body_bytes", 1024), TestClient(app) as c:
            r = c.get("/suites/quota")
        assert r.status_code == 200

    def test_the_default_fits_the_largest_honest_upload(self):
        """The starter suite's answers, at a few KB a response, are well
        under a megabyte. Two is room, not an invitation."""
        from evalbench.config import Settings

        assert Settings().max_body_bytes == 2 * 1024 * 1024


def _user(version=None, **extra):
    doc = {
        "username": "alice", "role": "user", "_id": "a",
        "hashed_password": get_password_hash("password-1"),
        **extra,
    }
    if version is not None:
        doc["token_version"] = version
    return doc


class TestSignOutMeansSignedOut:
    def test_a_fresh_token_carries_the_accounts_version(self, anon, mock_db):
        mock_db.users.find_one.return_value = _user(version=3)
        r = anon.post("/auth/login", data={"username": "alice", "password": "password-1"})
        from evalbench.api.auth import decode_token

        assert decode_token(r.json()["access_token"])["tv"] == 3

    def test_logout_bumps_the_version(self, mock_db):
        app.dependency_overrides[get_current_user] = lambda: ALICE
        with TestClient(app) as c:
            r = c.post("/auth/logout")
        assert r.status_code == 204
        assert mock_db.users.update_one.call_args[0] == (
            {"username": "alice"}, {"$inc": {"token_version": 1}},
        )

    def test_an_older_token_is_refused_after_that(self, anon, mock_db):
        """Minted at version 2; the account is at 3 now."""
        mock_db.users.find_one.return_value = _user(version=3)
        stale = create_access_token({"sub": "alice", "tv": 2})
        r = anon.get("/suites/quota", headers={"Authorization": f"Bearer {stale}"})
        assert r.status_code == 401
        assert "sign in again" in r.json()["detail"].lower()

    def test_the_current_token_still_works(self, anon, mock_db):
        mock_db.users.find_one.return_value = _user(version=3)
        current = create_access_token({"sub": "alice", "tv": 3})
        r = anon.get("/suites/quota", headers={"Authorization": f"Bearer {current}"})
        assert r.status_code == 200

    def test_a_token_from_before_versions_existed_is_version_zero(self, anon, mock_db):
        """Nobody is signed out by the deploy: an old token has no `tv`
        and an old account has no `token_version`; both read as 0 and
        match. The first sign-out moves the account to 1 and ends it."""
        mock_db.users.find_one.return_value = _user()  # no token_version
        old = create_access_token({"sub": "alice"})  # no tv
        r = anon.get("/suites/quota", headers={"Authorization": f"Bearer {old}"})
        assert r.status_code == 200
        mock_db.users.find_one.return_value = _user(version=1)
        r = anon.get("/suites/quota", headers={"Authorization": f"Bearer {old}"})
        assert r.status_code == 401

    def test_an_api_key_is_not_a_session_and_is_unaffected(self, anon, mock_db):
        """Keys are revoked by rotation, not by signing out of the site."""
        mock_db.users.find_one.return_value = _user(version=9)
        r = anon.get("/suites/quota", headers={"X-API-Key": "eb_whatever"})
        assert r.status_code == 200

    def test_a_password_reset_ends_every_session(self):
        """The CLI's reset-password is the recovery path for a lost — or
        stolen — password. Old sessions are the thing it should end."""
        from typer.testing import CliRunner

        from tests.test_reset_password import _fake_client

        client, users = _fake_client({"username": "alice", "role": "user"})
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            r = CliRunner().invoke(app_cli, ["reset-password", "-u", "alice", "-p", "new-password-1"])
        assert r.exit_code == 0, r.output
        update = users.update_one.await_args[0][1]
        assert update["$inc"] == {"token_version": 1}

    def test_expiry_is_still_the_backstop(self):
        expired = create_access_token({"sub": "alice", "tv": 0}, expires_delta=timedelta(seconds=-1))
        from evalbench.api.auth import decode_token

        assert decode_token(expired) is None


def test_the_register_model_documents_the_floor():
    assert auth_routes.UserCreate.model_fields["password"].metadata


def test_every_direct_import_is_a_declared_dependency():
    """Found live: swapping python-jose for PyJWT dropped `cryptography`
    from the image, and runkeys.py imports it — every run 500ed while
    the tests, on a venv that still had it, stayed green. Each top-level
    package the code imports must be named in pyproject, so the image
    and the venv cannot differ on what is installed."""
    import ast
    import pathlib
    import sys

    import tomllib

    pyproject = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
    declared = set()
    for dep in pyproject["project"]["dependencies"]:
        name = dep.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower()
        declared.add(name.replace("-", "_"))
    # distributions whose import name differs from their PyPI name
    aliases = {"yaml": "pyyaml", "jwt": "pyjwt", "dotenv": "python_dotenv",
               "motor": "motor", "bson": "pymongo", "rq": "rq", "redis": "redis",
               "sentence_transformers": "sentence_transformers", "sklearn": "scikit_learn",
               "prometheus_client": "prometheus_client", "slowapi": "slowapi",
               "typer": "typer", "rich": "rich", "httpx": "httpx", "passlib": "passlib",
               "pydantic_settings": "pydantic_settings", "pydantic": "pydantic",
               "fastapi": "fastapi", "uvicorn": "uvicorn", "numpy": "numpy", "scipy": "scipy",
               "cryptography": "cryptography", "multipart": "python_multipart"}
    stdlib = set(sys.stdlib_module_names)
    missing = {}
    for path in pathlib.Path("evalbench").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for n in names:
                if n in stdlib or n == "evalbench":
                    continue
                dist = aliases.get(n, n).lower()
                if dist not in declared:
                    missing.setdefault(n, str(path))
    assert not missing, f"imported but not declared in pyproject: {missing}"


class TestACrashIsStillAnAnswer:
    def test_a_500_carries_cors_headers_and_a_sentence(self, mock_db):
        """A crash inside a route produced a 500 with no CORS headers, so
        the browser hid it and the page could only say "Failed to fetch".
        The person then has nothing to report. The 500 now names itself
        and is readable from an allowed origin."""
        from fastapi import APIRouter

        from evalbench.api.main import app

        r = APIRouter()

        @r.get("/_boom")
        async def boom():
            raise RuntimeError("kaboom")

        app.include_router(r)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/_boom", headers={"Origin": "http://localhost:3005"})
        finally:
            app.router.routes[:] = [x for x in app.router.routes if getattr(x, "path", "") != "/_boom"]
        assert resp.status_code == 500
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3005"
        assert "API log" in resp.json()["detail"]
        assert "kaboom" not in resp.text  # the traceback stays in the log


class TestAUsernameIsAnEmail:
    """Sign-ups were any string: `amanku0801`, `x`, `admin2`. An account
    is now an email address — any real domain, not an allowlist, since
    the people worth signing up have company addresses — normalised so
    `Aman@Gmail.COM` and `aman@gmail.com` are one account. A format
    check, not proof: nothing is verified by mail yet."""

    def test_a_bare_handle_is_refused_with_an_example(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "amanku0801", "password": "secret123"})
        assert r.status_code == 422
        assert "email" in r.text.lower() and "you@" in r.text
        mock_db.users.insert_one.assert_not_called()

    @pytest.mark.parametrize("bad", ["x@y", "a b@gmail.com", "@gmail.com", "aman@", "aman@gmail..com"])
    def test_malformed_addresses_are_refused(self, anon, mock_db, bad):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": bad, "password": "secret123"})
        assert r.status_code == 422, bad

    @pytest.mark.parametrize("ok", ["aman@gmail.com", "a.b+tag@outlook.com", "recruiter@anthropic.com", "me@my-startup.io"])
    def test_any_real_domain_is_welcome(self, anon, mock_db, ok):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": ok, "password": "secret123"})
        assert r.status_code == 201, (ok, r.text)

    def test_the_address_is_stored_lowercased_and_trimmed(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "  Aman@Gmail.COM ", "password": "secret123"})
        assert r.status_code == 201
        assert mock_db.users.insert_one.call_args[0][0]["username"] == "aman@gmail.com"
        assert r.json()["username"] == "aman@gmail.com"
        # the duplicate check saw the normalised form too
        assert mock_db.users.find_one.call_args_list[0][0][0] == {"username": "aman@gmail.com"}

    def test_login_normalises_the_same_way(self, anon, mock_db):
        mock_db.users.find_one.return_value = _user(username="aman@gmail.com")
        r = anon.post("/auth/login", data={"username": "Aman@Gmail.COM", "password": "password-1"})
        assert r.status_code == 200
        assert mock_db.users.find_one.call_args_list[0][0][0] == {"username": "aman@gmail.com"}

    def test_existing_non_email_accounts_still_sign_in(self, anon, mock_db):
        """`admin` predates the rule and is looked up as typed."""
        mock_db.users.find_one.return_value = _user(username="admin")
        r = anon.post("/auth/login", data={"username": "admin", "password": "password-1"})
        assert r.status_code == 200
