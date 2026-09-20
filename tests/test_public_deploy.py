"""What has to hold before the instance is on the internet with a key in it.

None of the keys can produce a bill — they are card-less free tiers — so
the thing to protect is the quota, and the database. The per-user cap
protects the key from one greedy account; nothing protected it from many
accounts, because registration was open, unlimited and unlimited per
address. And a database leak handed out every account, because the API
keys were stored in the clear.

Four controls, each tested here: registration can be closed and is rate
limited; an instance-wide daily cap on server-key runs; an account the
admin bans cannot come back from the addresses it used; user API keys are
stored as hashes. Plus the compose file: Mongo and Redis on loopback.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from evalbench.api import auth_routes, routes
from evalbench.api.deps import get_current_user, limiter
from evalbench.api.main import app

ALICE = {"username": "alice", "role": "user", "_id": "a"}
ADMIN = {"username": "admin", "role": "admin", "_id": "0"}


def _sha(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@pytest.fixture
def anon(mock_db):
    """A client with no user override, from a fixed address."""
    saved = app.dependency_overrides.pop(get_current_user, None)
    with TestClient(app, client=("203.0.113.9", 4242)) as c:
        yield c
    if saved:
        app.dependency_overrides[get_current_user] = saved


def _as(user, mock_db, addr=("203.0.113.9", 4242)):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, client=addr)


# ── registration ──────────────────────────────────────────────────────


class TestRegistrationCanBeClosed:
    def test_open_by_default_so_a_fresh_install_has_a_way_in(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "new", "password": "secret123"})
        assert r.status_code == 201

    def test_closed_means_403_with_a_way_forward(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        with patch.object(auth_routes.settings, "allow_registration", False):
            r = anon.post("/auth/register", json={"username": "new", "password": "secret123"})
        assert r.status_code == 403
        assert "closed" in r.json()["detail"].lower()
        assert "admin" in r.json()["detail"].lower()
        mock_db.users.insert_one.assert_not_called()

    def test_the_route_is_rate_limited(self):
        """slowapi is disabled under test, so the limit is checked as
        registered rather than exercised: five an hour per address is
        plenty for a person and nothing for a script."""
        limits = limiter._route_limits.get("evalbench.api.auth_routes.register")
        assert limits, "no rate limit registered on /auth/register"
        assert str(limits[0].limit) == "5 per 1 hour"


# ── the ban, and the addresses it used ────────────────────────────────


class TestABannedAccountStaysGone:
    def test_registering_stores_the_address(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        anon.post("/auth/register", json={"username": "new", "password": "secret123"})
        doc = mock_db.users.insert_one.call_args[0][0]
        assert doc["ips"] == ["203.0.113.9"]

    def test_logging_in_records_the_address(self, anon, mock_db):
        from evalbench.api.auth import get_password_hash

        mock_db.users.find_one.return_value = {
            "username": "alice", "hashed_password": get_password_hash("pw"), "role": "user",
        }
        r = anon.post("/auth/login", data={"username": "alice", "password": "pw"})
        assert r.status_code == 200
        update = mock_db.users.update_one.call_args[0][1]
        assert update["$addToSet"] == {"ips": "203.0.113.9"}
        assert update["$set"]["last_ip"] == "203.0.113.9"

    def test_a_deactivated_account_cannot_log_in(self, anon, mock_db):
        from evalbench.api.auth import get_password_hash

        mock_db.users.find_one.return_value = {
            "username": "bob", "hashed_password": get_password_hash("pw"),
            "role": "user", "active": False,
        }
        r = anon.post("/auth/login", data={"username": "bob", "password": "pw"})
        assert r.status_code == 403
        assert "deactivated" in r.json()["detail"].lower()

    def test_a_new_account_from_a_banned_address_is_refused(self, anon, mock_db):
        """The name is free; the address is one a banned account used."""

        async def find_one(query, *a, **k):
            if "username" in query:
                return None
            if query.get("active") is False and "ips" in query:
                return {"username": "bob", "active": False, "ips": ["203.0.113.9"]}
            return None

        mock_db.users.find_one.side_effect = find_one
        r = anon.post("/auth/register", json={"username": "bob2", "password": "secret123"})
        assert r.status_code == 403
        assert "address" in r.json()["detail"].lower()
        mock_db.users.insert_one.assert_not_called()

    def test_the_lookup_is_by_this_address_only(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        anon.post("/auth/register", json={"username": "new", "password": "secret123"})
        queries = [c[0][0] for c in mock_db.users.find_one.call_args_list]
        assert {"active": False, "ips": "203.0.113.9"} in queries

    def test_behind_a_proxy_the_forwarded_address_counts_only_when_trusted(self, mock_db):
        """A client can send X-Forwarded-For itself. It is read only when
        the operator says there is a proxy in front; otherwise the socket
        address is the truth, whatever the header says."""
        from evalbench.api.deps import client_ip

        req = MagicMock()
        req.client.host = "10.0.0.2"
        req.headers = {"x-forwarded-for": "198.51.100.7, 10.0.0.1"}
        with patch.object(routes.settings, "trust_proxy", False):
            assert client_ip(req) == "10.0.0.2"
        with patch.object(routes.settings, "trust_proxy", True):
            assert client_ip(req) == "198.51.100.7"

    def test_the_admin_list_shows_addresses_but_never_a_key(self, mock_db):
        with _as(ADMIN, mock_db) as c:
            c.get("/admin/users")
        projection = mock_db.users.find.call_args[0][1]
        assert projection["api_key"] == 0
        assert projection["api_key_hash"] == 0
        assert projection.get("ips", 1) == 1


# ── the instance-wide cap ─────────────────────────────────────────────

SUITE_ID = "507f1f77bcf86cd799439011"
SUITE = {
    "_id": SUITE_ID, "name": "S", "provider": "groq", "model": "openai/gpt-oss-20b",
    "evaluator": "exact", "created_by": "alice", "samples": 1,
    "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
}


def _counts(per_user: int, total: int):
    """count_documents answers differently for 'this user' and 'everyone'."""

    async def count(query, *a, **k):
        if query.get("used_server_key"):
            return per_user if "created_by" in query else total
        return 0

    return count


class TestTheInstanceCap:
    def test_everyone_together_cannot_exceed_it(self, mock_db):
        """Alice has used 1 of her 20; the instance has used its 200.
        Her run is refused, and the reason is the shared limit, not hers."""
        mock_db.suites.find_one.return_value = dict(SUITE)
        mock_db.test_runs.count_documents.side_effect = _counts(1, 200)
        with patch.object(routes.settings, "daily_run_cap_total", 200), _as(ALICE, mock_db) as c:
            r = c.post(f"/suites/{SUITE_ID}/run", json={})
        assert r.status_code == 429
        assert "everyone" in r.json()["detail"].lower()
        mock_db.test_runs.insert_one.assert_not_called()

    def test_a_caller_with_their_own_key_is_not_counted(self, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE)
        mock_db.test_runs.count_documents.side_effect = _counts(1, 200)
        mock_db.test_runs.insert_one.return_value.inserted_id = "6ab0000000000000000000aa"
        with (
            patch.object(routes.settings, "daily_run_cap_total", 200),
            patch.object(routes, "submit_run"),
            _as(ALICE, mock_db) as c,
        ):
            r = c.post(f"/suites/{SUITE_ID}/run", json={"provider_key": "gsk_theirs"})
        assert r.status_code == 202

    def test_zero_means_no_instance_cap(self, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE)
        mock_db.test_runs.count_documents.side_effect = _counts(1, 10_000)
        mock_db.test_runs.insert_one.return_value.inserted_id = "6ab0000000000000000000aa"
        with (
            patch.object(routes.settings, "daily_run_cap_total", 0),
            patch.object(routes, "submit_run"),
            _as(ALICE, mock_db) as c,
        ):
            r = c.post(f"/suites/{SUITE_ID}/run", json={})
        assert r.status_code == 202

    def test_the_quota_reports_the_tighter_of_the_two(self, mock_db):
        """Alice has 19 of 20 left; the instance has 3 of 200. She sees 3,
        and is told why."""
        mock_db.test_runs.count_documents.side_effect = _counts(1, 197)
        with patch.object(routes.settings, "daily_run_cap_total", 200), _as(ALICE, mock_db) as c:
            body = c.get("/suites/quota").json()
        assert body["remaining"] == 3
        assert body["cap"] == routes.settings.daily_run_cap
        assert body["instance"] == {"cap": 200, "used": 197, "remaining": 3}

    def test_admins_are_not_counted_against_it(self, mock_db):
        mock_db.suites.find_one.return_value = {**SUITE, "created_by": "admin"}
        mock_db.test_runs.count_documents.side_effect = _counts(0, 200)
        mock_db.test_runs.insert_one.return_value.inserted_id = "6ab0000000000000000000aa"
        with (
            patch.object(routes.settings, "daily_run_cap_total", 200),
            patch.object(routes, "submit_run"),
            _as(ADMIN, mock_db) as c,
        ):
            r = c.post(f"/suites/{SUITE_ID}/run", json={})
        assert r.status_code == 202


# ── hashed API keys ───────────────────────────────────────────────────


class TestApiKeysAreStoredHashed:
    def test_registration_stores_the_hash_and_returns_the_key_once(self, anon, mock_db):
        mock_db.users.find_one.return_value = None
        r = anon.post("/auth/register", json={"username": "new", "password": "secret123"})
        key = r.json()["api_key"]
        doc = mock_db.users.insert_one.call_args[0][0]
        assert "api_key" not in doc
        assert doc["api_key_hash"] == _sha(key)

    def test_a_request_with_a_key_is_looked_up_by_its_hash(self, anon, mock_db):
        mock_db.users.find_one.return_value = {**ALICE, "_id": "a"}
        anon.get("/suites/quota", headers={"X-API-Key": "eb_secret"})
        queries = [c[0][0] for c in mock_db.users.find_one.call_args_list]
        assert {"api_key_hash": _sha("eb_secret")} in queries
        assert not any("api_key" in q for q in queries)

    def test_rotating_replaces_the_hash_and_drops_any_plaintext(self, mock_db):
        with _as(ALICE, mock_db) as c:
            r = c.post("/auth/api-key/rotate")
        new = r.json()["api_key"]
        update = mock_db.users.update_one.call_args[0][1]
        assert update["$set"] == {"api_key_hash": _sha(new)}
        assert update["$unset"] == {"api_key": ""}

    def test_the_admin_is_bootstrapped_with_a_hash(self, mock_db):
        from evalbench.api import main

        mock_db.users.count_documents.return_value = 0
        with (
            patch.object(main, "db", mock_db),
            patch.object(main.settings, "job_backend", "inline"),
            patch.object(main.settings, "admin_api_key", "eb_admin_real"),
        ):
            import asyncio

            asyncio.run(main._bootstrap_admin())
        doc = mock_db.users.insert_one.call_args[0][0]
        assert "api_key" not in doc
        assert doc["api_key_hash"] == _sha("eb_admin_real")

    @pytest.mark.asyncio
    async def test_startup_hashes_every_key_stored_in_the_clear(self, mock_db):
        """Accounts made before this carry `api_key`. Each becomes a hash
        and the plaintext is removed, so the key keeps working and the
        database no longer holds it."""
        from evalbench.api import main

        legacy = [
            {"_id": "1", "username": "old", "api_key": "eb_old"},
            {"_id": "2", "username": "older", "api_key": "eb_older"},
        ]

        class _Cursor:
            def __init__(self, docs):
                self._docs = docs

            def __aiter__(self):
                async def gen():
                    for d in self._docs:
                        yield d
                return gen()

        mock_db.users.find.return_value = _Cursor(legacy)
        with patch.object(main, "db", mock_db):
            n = await main._backfill_api_key_hashes()
        assert n == 2
        calls = [c[0] for c in mock_db.users.update_one.call_args_list]
        assert ({"_id": "1"}, {"$set": {"api_key_hash": _sha("eb_old")}, "$unset": {"api_key": ""}}) in calls
        assert mock_db.users.find.call_args[0][0] == {"api_key": {"$exists": True}}

    @pytest.mark.asyncio
    async def test_the_unique_index_moves_to_the_hash(self, mock_db):
        from evalbench.api.main import _ensure_indexes

        await _ensure_indexes()
        created = {c[0][0]: c[1] for c in mock_db.users.create_index.call_args_list}
        assert created["api_key_hash"].get("unique") is True
        assert "api_key" not in created


# ── the compose file ──────────────────────────────────────────────────


class TestComposeBindsStateToLoopback:
    def test_mongo_and_redis_are_not_on_every_interface(self):
        """A compose file copied to a VPS as-is put the database and the
        key stash on the internet, unauthenticated. The browser never
        talks to either; only other containers do, over the compose
        network. Publishing on 127.0.0.1 keeps `mongosh` and `redis-cli`
        working from the host and nothing else."""
        compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))
        for svc in ("mongo", "redis", "ollama", "prometheus"):
            for port in compose["services"][svc].get("ports", []):
                assert str(port).startswith("127.0.0.1:"), f"{svc} publishes {port} on all interfaces"

    def test_what_the_browser_needs_stays_reachable(self):
        compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))
        for svc in ("api", "web", "grafana"):
            ports = compose["services"][svc]["ports"]
            assert ports and not str(ports[0]).startswith("127.0.0.1:")
