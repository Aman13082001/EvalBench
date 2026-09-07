"""`evalbench reset-password` — the way back from an admin lockout.

The web app authenticates with a username and password only. An admin who
does not know the admin password could not reach /admin at all, and no
reset existed anywhere in the CLI or the API, so the only route back was
dropping the users collection.

Two design points these tests hold in place:

* It writes straight to MongoDB rather than calling an endpoint. Database
  access is the proof of authority for resetting an account, and it means
  there is no unauthenticated reset route on the API to attack.
* It says which database it is writing to, and on a miss it names the
  accounts that database does hold. A machine can have a second MongoDB —
  a locally installed service alongside the one Docker publishes on the
  same port — and then "no such user" really means "wrong database".
  That happened during development and was baffling until the command
  said so.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from evalbench.cli import app

runner = CliRunner()


def _fake_client(user: dict | None, others: list[str] | None = None):
    """A motor client stand-in wired for one users collection."""
    users = MagicMock()
    users.find_one = AsyncMock(return_value=user)
    users.update_one = AsyncMock()

    class _Cursor:
        def __aiter__(self):
            async def gen():
                for name in others or []:
                    yield {"username": name}

            return gen()

    users.find = MagicMock(return_value=_Cursor())

    db = MagicMock()
    db.users = users
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.close = MagicMock()
    return client, users


class TestSuccess:
    def test_resets_and_reports_the_role(self):
        client, users = _fake_client({"username": "admin", "role": "admin"})
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            r = runner.invoke(
                app, ["reset-password", "-u", "admin", "-p", "s3cret-pw"]
            )
        assert r.exit_code == 0, r.output
        assert "admin" in r.output and "role: admin" in r.output
        users.update_one.assert_awaited_once()

    def test_password_is_hashed_never_stored_raw(self):
        """The obvious catastrophic bug for this command."""
        client, users = _fake_client({"username": "admin", "role": "admin"})
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            runner.invoke(
                app, ["reset-password", "-u", "admin", "-p", "s3cret-pw"]
            )
        written = users.update_one.await_args[0][1]["$set"]
        assert written["hashed_password"] != "s3cret-pw"
        assert "s3cret-pw" not in written["hashed_password"]
        from evalbench.api.auth import verify_password

        assert verify_password("s3cret-pw", written["hashed_password"])

    def test_reactivates_a_disabled_account(self):
        """A locked-out account is often also a deactivated one; leaving
        active=False would fix the password and still refuse the login."""
        client, users = _fake_client({"username": "a", "role": "user"})
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            runner.invoke(app, ["reset-password", "-u", "a", "-p", "pw123456"])
        assert users.update_one.await_args[0][1]["$set"]["active"] is True

    def test_names_the_database_before_writing(self):
        client, _ = _fake_client({"username": "admin", "role": "admin"})
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            r = runner.invoke(
                app, ["reset-password", "-u", "admin", "-p", "pw123456"]
            )
        assert "Database:" in r.output


class TestMisses:
    def test_unknown_user_lists_who_is_actually_there(self):
        client, users = _fake_client(None, others=["admin", "someone-else"])
        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            r = runner.invoke(
                app, ["reset-password", "-u", "ghost", "-p", "pw123456"]
            )
        assert r.exit_code == 1
        assert "someone-else" in r.output
        assert "wrong MongoDB" in r.output
        users.update_one.assert_not_awaited()

    def test_unreachable_database_says_so(self):
        with patch(
            "motor.motor_asyncio.AsyncIOMotorClient",
            side_effect=RuntimeError("connection refused"),
        ):
            r = runner.invoke(
                app, ["reset-password", "-u", "admin", "-p", "pw123456"]
            )
        assert r.exit_code == 1
        assert "Couldn't reach the database" in r.output


def test_no_reset_endpoint_is_exposed_on_the_api():
    """Recovery must require database access, not an HTTP call. An
    unauthenticated reset route would be a takeover primitive."""
    from evalbench.api.main import app as api

    paths = {getattr(r, "path", "") for r in api.routes}
    assert not [p for p in paths if "reset" in p.lower()], (
        "password reset must stay off the API surface"
    )
