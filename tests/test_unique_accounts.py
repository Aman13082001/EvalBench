"""One username, one account — enforced by the database, not by a check.

Registration read `find_one({"username": ...})`, decided the name was
free, and then inserted. Between those two statements another request can
do exactly the same, and the index carried no uniqueness constraint to
stop the second write. Two accounts then share a username, and
`find_one` at login returns whichever Mongo happens to reach first — so
you can sign in and find yourself in the other account's suites and runs.

A check cannot make this safe no matter how carefully it is written; the
constraint has to live where the write does. The check stays only to
turn the database's error into a decent message.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

from evalbench.api.main import app


@pytest.fixture
def client(mock_db):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


class TestTheConstraintExists:
    @pytest.mark.asyncio
    async def test_username_and_api_key_are_unique_indexes(self, mock_db):
        """The index is the only thing standing between two simultaneous
        registrations and two accounts with one name."""
        from evalbench.api import main

        with patch.object(main, "db", mock_db), patch.object(
            main.settings, "job_backend", "inline"
        ):
            async with main.lifespan(app):
                pass

        created = {
            c[0][0]: c[1] for c in mock_db.users.create_index.call_args_list
        }
        assert created["username"].get("unique") is True
        assert created["api_key"].get("unique") is True


class TestTheRace:
    def test_a_lost_race_reads_as_a_taken_name(self, client, mock_db):
        """The other request won by microseconds. From here that is
        indistinguishable from the name having been taken earlier, and it
        should read the same to the person registering."""
        mock_db.users.find_one.return_value = None  # free, a moment ago
        mock_db.users.insert_one = AsyncMock(
            side_effect=DuplicateKeyError("username already exists")
        )

        r = client.post(
            "/auth/register", json={"username": "alice", "password": "pw12345678"}
        )
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"].lower()

    def test_the_early_check_still_answers_first(self, client, mock_db):
        """The database is the guarantee, but an existing name should not
        need a failed insert to be reported."""
        mock_db.users.find_one.return_value = {"username": "alice"}
        r = client.post(
            "/auth/register", json={"username": "alice", "password": "pw12345678"}
        )
        assert r.status_code == 400
        mock_db.users.insert_one.assert_not_called()

    def test_a_free_name_still_registers(self, client, mock_db):
        mock_db.users.find_one.return_value = None
        mock_db.users.insert_one = AsyncMock()
        r = client.post(
            "/auth/register", json={"username": "bob", "password": "pw12345678"}
        )
        assert r.status_code in (200, 201), r.text
        assert "api_key" in r.json()


class TestUpgradingAnExistingDatabase:
    """Adding `unique` to an index that already exists is not a no-op:
    MongoDB refuses with IndexKeySpecsConflict, and the API would not
    start at all. Every database created before this change has the old
    index, so the upgrade path is part of the fix, not an afterthought."""

    @pytest.mark.asyncio
    async def test_it_rebuilds_an_index_that_exists_without_unique(self):
        from unittest.mock import MagicMock

        from pymongo.errors import OperationFailure

        from evalbench.api.main import ensure_unique_index

        coll = MagicMock()
        conflict = OperationFailure("conflict", code=85)
        coll.create_index = AsyncMock(side_effect=[conflict, "username_1"])
        coll.drop_index = AsyncMock()

        assert await ensure_unique_index(coll, "username") is True
        coll.drop_index.assert_awaited_once_with("username_1")
        assert coll.create_index.await_count == 2

    @pytest.mark.asyncio
    async def test_existing_duplicates_do_not_stop_the_api_starting(self):
        """If two accounts already share a name the constraint cannot be
        built. Refusing to boot would lock the operator out of the very
        tools needed to merge them, so it starts and says so loudly."""
        from unittest.mock import MagicMock

        from pymongo.errors import DuplicateKeyError

        from evalbench.api.main import ensure_unique_index

        coll = MagicMock()
        coll.create_index = AsyncMock(side_effect=DuplicateKeyError("dupes"))
        coll.drop_index = AsyncMock()

        assert await ensure_unique_index(coll, "username") is False

    @pytest.mark.asyncio
    async def test_a_fresh_database_just_builds_it(self):
        from unittest.mock import MagicMock

        from evalbench.api.main import ensure_unique_index

        coll = MagicMock()
        coll.create_index = AsyncMock(return_value="username_1")
        coll.drop_index = AsyncMock()

        assert await ensure_unique_index(coll, "username") is True
        coll.drop_index.assert_not_awaited()
