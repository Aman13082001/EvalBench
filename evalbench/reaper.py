"""Deciding which runs are dead, without guessing.

A run left `queued` or `running` with nothing executing it would hang
for ever, so something has to fail it. The question is what counts as
proof of death, and that depends on where the work happens.

``JOB_BACKEND=inline`` runs the suite inside the API process: if the API
restarted, every unfinished run really did die with it. ``rq`` runs it in
a separate worker container that restarts on its own schedule, so an API
restart proves nothing — reaping on that signal marked live runs as
failed on every deploy, and the worker then wrote ``completed`` over
them. Under rq the only honest evidence is silence: a run that has
stopped reporting progress for longer than any single test could take.

A queued rq job is deliberately left alone. It lives in Redis, which the
API cannot see; failing it would be a guess, and the worker would run it
afterwards regardless.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# How long a run may go without reporting progress before it is presumed
# dead. Generous on purpose: one slow test — a large model, a retried
# rate limit, a cold Ollama load — must never look like a dead worker.
STALE_AFTER = timedelta(minutes=15)


def reap_filter(backend: str, now: datetime) -> dict | None:
    """The Mongo filter matching runs that can be proven dead.

    ``None`` when the backend is unrecognised: an unknown execution model
    means no basis for the claim, and failing someone's live run is worse
    than leaving a stuck one.
    """
    if backend == "inline":
        # The work happened here. Nothing survives the process.
        return {"status": {"$in": ["queued", "running"]}}

    if backend == "rq":
        cutoff = now - STALE_AFTER
        return {
            "status": "running",
            "$or": [
                {"heartbeat_at": {"$lt": cutoff}},
                # No heartbeat at all: stored before heartbeats existed,
                # or killed between claiming the job and finishing its
                # first test. Judge it by when it started instead.
                {
                    "heartbeat_at": {"$exists": False},
                    "started_at": {"$lt": cutoff},
                },
            ],
        }

    return None


def reap_reason(backend: str) -> str:
    """What to record on a reaped run, in the words of what happened."""
    if backend == "inline":
        return "interrupted by an API restart"
    return (
        "no progress reported for "
        f"{int(STALE_AFTER.total_seconds() // 60)} minutes — "
        "the worker running it appears to have stopped"
    )
