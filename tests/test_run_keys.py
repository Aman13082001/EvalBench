"""A caller's provider key lives only while its run executes — nowhere else.

The key was passed to RQ as a job argument. RQ persists job arguments —
pickled, in `rq:job:<id>` — and keeps a *failed* job at its default
failure_ttl of one year. Verified on the running stack: a failed job's
TTL was 31,108,291 seconds. So a user who pasted a key and hit a rate
limit had that key sitting in Redis, in plaintext, for 360 days. The
existing test asserted the key never reaches Mongo, which was true and
beside the point: Redis is a database too.

Now the key is written once, encrypted, under its own name with its own
short lifetime; the job carries only the run id; the worker reads it,
and deletes it the moment the run can no longer need it.
"""

from unittest.mock import MagicMock, patch

import pytest

from evalbench import runkeys

KEY = "gsk_this_is_a_real_looking_secret_0123456789"
RUN = "507f191e810c19729de860ea"


class FakeRedis:
    """Just enough of redis-py for these tests: values, TTLs, scan."""

    def __init__(self):
        self.store: dict[bytes, bytes] = {}
        self.ttls: dict[bytes, int] = {}

    def set(self, name, value, ex=None):
        n = name.encode() if isinstance(name, str) else name
        self.store[n] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.ttls[n] = int(ex)

    def get(self, name):
        n = name.encode() if isinstance(name, str) else name
        return self.store.get(n)

    def delete(self, *names):
        for name in names:
            n = name.encode() if isinstance(name, str) else name
            self.store.pop(n, None)
            self.ttls.pop(n, None)

    def ttl(self, name):
        n = name.encode() if isinstance(name, str) else name
        return self.ttls.get(n, -1)

    def scan_iter(self, match="*"):
        return iter(list(self.store))

    def everything(self) -> bytes:
        """Every byte stored, for "the key is nowhere in here" checks."""
        return b"".join(self.store) + b"".join(self.store.values())


@pytest.fixture
def redis():
    return FakeRedis()


class TestTheKeyAtRest:
    def test_it_is_not_stored_in_the_clear(self, redis):
        runkeys.stash(redis, RUN, KEY)
        assert KEY.encode() not in redis.everything()

    def test_it_round_trips(self, redis):
        runkeys.stash(redis, RUN, KEY)
        assert runkeys.take(redis, RUN) == KEY

    def test_it_expires_on_its_own(self, redis):
        """The TTL is the guarantee; the explicit delete is a courtesy.
        Whatever else goes wrong, the key cannot outlive it."""
        runkeys.stash(redis, RUN, KEY)
        assert 0 < redis.ttl(runkeys.name(RUN)) <= runkeys.TTL_SECONDS
        assert runkeys.TTL_SECONDS <= 24 * 3600

    def test_a_missing_key_reads_as_none_not_an_error(self, redis):
        assert runkeys.take(redis, "nope") is None

    def test_a_ciphertext_from_another_secret_is_refused(self, redis):
        """Rotating SECRET_KEY must invalidate stashed keys rather than
        hand back garbage — or worse, someone else's ciphertext."""
        runkeys.stash(redis, RUN, KEY)
        with patch.object(runkeys, "_fernet", return_value=runkeys._fernet_for("other")):
            assert runkeys.take(redis, RUN) is None

    def test_discard_removes_it(self, redis):
        runkeys.stash(redis, RUN, KEY)
        runkeys.discard(redis, RUN)
        assert redis.get(runkeys.name(RUN)) is None


class TestTheJobCarriesOnlyTheRunId:
    def test_enqueue_never_puts_the_key_in_the_job(self, redis):
        """RQ persists job arguments for as long as it keeps the job. The
        only argument that is safe to persist is one that is not a
        secret."""
        from evalbench import jobs_rq

        queue = MagicMock()
        with patch.object(jobs_rq, "_queue", return_value=queue), patch.object(
            jobs_rq, "_redis", return_value=redis
        ):
            jobs_rq.enqueue_run(RUN, "suite-1", KEY)

        args = queue.enqueue.call_args
        assert KEY not in repr(args)
        assert args[0][1:] == (RUN, "suite-1")  # function, then only these
        # and it went where it belongs instead
        assert runkeys.take(redis, RUN) == KEY

    def test_no_key_means_nothing_is_stashed(self, redis):
        from evalbench import jobs_rq

        queue = MagicMock()
        with patch.object(jobs_rq, "_queue", return_value=queue), patch.object(
            jobs_rq, "_redis", return_value=redis
        ):
            jobs_rq.enqueue_run(RUN, "suite-1", None)
        assert redis.store == {}


class TestTheWorkerCleansUp:
    def _run(self, redis, outcome, retries_left=0):
        from evalbench import jobs_rq

        seen = {}

        async def fake_execute(run_id, suite_id, provider_key=None):
            seen["key"] = provider_key
            if outcome == "fail":
                raise RuntimeError("provider exploded")

        job = MagicMock(retries_left=retries_left)
        with patch.object(jobs_rq, "_redis", return_value=redis), patch(
            "evalbench.jobs.execute_run_job", fake_execute
        ), patch.object(jobs_rq, "get_current_job", return_value=job), patch(
            "evalbench.db.mongo.make_client", return_value=MagicMock()
        ):
            try:
                jobs_rq.run_job_sync(RUN, "suite-1")
            except RuntimeError:
                pass
        return seen

    def test_the_worker_reads_it_and_uses_it(self, redis):
        runkeys.stash(redis, RUN, KEY)
        seen = self._run(redis, "ok")
        assert seen["key"] == KEY

    def test_a_finished_run_deletes_it(self, redis):
        runkeys.stash(redis, RUN, KEY)
        self._run(redis, "ok")
        assert redis.get(runkeys.name(RUN)) is None
        assert KEY.encode() not in redis.everything()

    def test_a_failed_run_with_retries_left_keeps_it(self, redis):
        """RQ will run the job again in a moment; it needs the key then.
        The TTL still bounds how long that can go on."""
        runkeys.stash(redis, RUN, KEY)
        self._run(redis, "fail", retries_left=2)
        assert runkeys.take(redis, RUN) == KEY

    def test_a_finally_failed_run_deletes_it(self, redis):
        """This is the case that leaked for a year: the job that failed
        and would never run again, still holding the key."""
        runkeys.stash(redis, RUN, KEY)
        self._run(redis, "fail", retries_left=0)
        assert KEY.encode() not in redis.everything()

    def test_an_old_job_that_still_carries_a_key_is_honoured(self, redis):
        """Jobs queued before this change have the key as an argument.
        Refusing them would fail every run in flight during a deploy."""
        from evalbench import jobs_rq

        seen = {}

        async def fake_execute(run_id, suite_id, provider_key=None):
            seen["key"] = provider_key

        with patch.object(jobs_rq, "_redis", return_value=redis), patch(
            "evalbench.jobs.execute_run_job", fake_execute
        ), patch.object(jobs_rq, "get_current_job", return_value=None), patch(
            "evalbench.db.mongo.make_client", return_value=MagicMock()
        ):
            jobs_rq.run_job_sync(RUN, "suite-1", KEY)
        assert seen["key"] == KEY


def test_the_name_is_namespaced():
    """Nothing else in Redis should be able to collide with, or be
    mistaken for, a stashed key."""
    assert runkeys.name(RUN).startswith("evalbench:runkey:")
    assert RUN in runkeys.name(RUN)
