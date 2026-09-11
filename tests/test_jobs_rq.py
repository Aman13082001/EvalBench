"""RQ dispatch path (JOB_BACKEND=rq)."""

from unittest.mock import MagicMock, patch

from evalbench.jobs import submit_run

RUN_ID = "507f1f77bcf86cd799439011"
SUITE_ID = "507f191e810c19729de860ea"


def test_submit_run_inline_uses_background_tasks(monkeypatch):
    from evalbench.jobs import settings

    monkeypatch.setattr(settings, "job_backend", "inline")
    bg = MagicMock()
    submit_run(RUN_ID, SUITE_ID, bg)
    bg.add_task.assert_called_once()


def test_submit_run_rq_enqueues(monkeypatch):
    from evalbench.jobs import settings

    monkeypatch.setattr(settings, "job_backend", "rq")
    with patch("evalbench.jobs_rq.enqueue_run") as enq:
        submit_run(RUN_ID, SUITE_ID, MagicMock())
    enq.assert_called_once_with(RUN_ID, SUITE_ID, None)


def test_enqueue_run_calls_queue_with_job_id():
    q = MagicMock()
    with patch("evalbench.jobs_rq._queue", return_value=q):
        from evalbench.jobs_rq import enqueue_run

        enqueue_run(RUN_ID, SUITE_ID)

    args, kwargs = q.enqueue.call_args
    assert args[0] == "evalbench.jobs_rq.run_job_sync"
    assert args[1:] == (RUN_ID, SUITE_ID, None)
    assert kwargs["job_id"] == RUN_ID


def test_run_job_sync_runs_the_async_job():
    called = {}

    async def _fake(run_id, suite_id, provider_key=None):
        called["args"] = (run_id, suite_id, provider_key)

    with (
        patch("evalbench.jobs.execute_run_job", _fake),
        patch("evalbench.db.mongo.make_client", return_value=MagicMock()),
    ):
        from evalbench.jobs_rq import run_job_sync

        run_job_sync(RUN_ID, SUITE_ID)

    assert called["args"] == (RUN_ID, SUITE_ID, None)


def test_own_key_travels_as_a_job_argument_not_a_document_field():
    """A caller's provider key must reach the runner but never be written
    to Mongo. Passing it as a job argument is how both hold at once."""
    q = MagicMock()
    with patch("evalbench.jobs_rq._queue", return_value=q):
        from evalbench.jobs_rq import enqueue_run

        enqueue_run(RUN_ID, SUITE_ID, "gsk_user_key")

    args, _ = q.enqueue.call_args
    assert args[1:] == (RUN_ID, SUITE_ID, "gsk_user_key")
