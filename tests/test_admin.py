"""Admin endpoints: user management and system stats."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app

PLAIN = {"username": "alice", "role": "user", "_id": "a"}


@pytest.fixture
def as_plain_user(mock_db):
    app.dependency_overrides[get_current_user] = lambda: PLAIN
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


def _users_cursor(docs):
    async def gen():
        for d in docs:
            yield d

    return gen()


class TestAdminAccess:
    def test_plain_user_is_forbidden(self, as_plain_user):
        assert as_plain_user.get("/admin/users").status_code == 403
        assert as_plain_user.get("/admin/stats").status_code == 403

    def test_admin_allowed(self, client, mock_db):
        mock_db.users.find.return_value.sort.return_value = _users_cursor([])
        assert client.get("/admin/users").status_code == 200


class TestListUsers:
    def test_never_leaks_secrets(self, client, mock_db):
        mock_db.users.find.return_value.sort.return_value = _users_cursor(
            [{"_id": "1", "username": "alice", "role": "user"}]
        )
        r = client.get("/admin/users")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["users"][0]["active"] is True  # defaulted
        # the projection must exclude these
        projection = mock_db.users.find.call_args[0][1]
        assert projection["hashed_password"] == 0
        assert projection["api_key"] == 0


class TestActivation:
    def test_deactivate(self, client, mock_db):
        mock_db.users.update_one.return_value = MagicMock(matched_count=1)
        r = client.post("/admin/users/bob/deactivate")
        assert r.status_code == 200
        assert r.json() == {"username": "bob", "active": False}
        assert mock_db.users.update_one.call_args[0][1] == {
            "$set": {"active": False}
        }

    def test_activate(self, client, mock_db):
        mock_db.users.update_one.return_value = MagicMock(matched_count=1)
        r = client.post("/admin/users/bob/activate")
        assert r.json()["active"] is True

    def test_unknown_user_404(self, client, mock_db):
        mock_db.users.update_one.return_value = MagicMock(matched_count=0)
        assert client.post("/admin/users/ghost/deactivate").status_code == 404

    def test_cannot_lock_yourself_out(self, client, mock_db):
        # conftest's admin override is username "testuser"
        r = client.post("/admin/users/testuser/deactivate")
        assert r.status_code == 400
        assert "your own account" in r.json()["detail"]


class TestStats:
    def test_counts_and_spend(self, client, mock_db):
        mock_db.users.count_documents.return_value = 3
        mock_db.suites.count_documents.return_value = 5
        mock_db.test_runs.count_documents.return_value = 9

        # Spend and the status breakdown are aggregations now: Mongo
        # sums them, rather than this process reading every run.
        def aggregate(pipeline, *a, **k):
            unwinds = any("$unwind" in stage for stage in pipeline)

            async def gen():
                if unwinds:
                    yield {"_id": None, "total": 0.0035}
                else:
                    yield {"_id": "completed", "n": 9}

            return gen()

        mock_db.test_runs.aggregate = aggregate

        r = client.get("/admin/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["users"] == 3
        assert body["suites"] == 5
        assert body["total_cost_usd"] == pytest.approx(0.0035)
        assert set(body["runs_by_status"]) == {
            "queued",
            "running",
            "completed",
            "failed",
        }


class TestDeactivatedUsersCannotAuthenticate:
    @pytest.mark.asyncio
    async def test_inactive_is_rejected(self):
        from fastapi import HTTPException

        from evalbench.api.deps import _accept

        with pytest.raises(HTTPException) as exc:
            _accept({"_id": "1", "username": "bob", "active": False})
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_active_and_legacy_pass(self):
        from evalbench.api.deps import _accept

        assert _accept({"_id": "1", "username": "a", "active": True})
        # documents written before the flag existed stay usable
        assert _accept({"_id": "1", "username": "a"})
