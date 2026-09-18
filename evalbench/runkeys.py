"""Where a caller's provider key lives while its run executes — and nowhere else.

A run on someone's own key has to get that key from the API to the
worker. It used to travel as an RQ job argument, and RQ persists job
arguments: pickled, in ``rq:job:<id>``, for as long as it keeps the job.
For a *failed* job the default is a year. Measured on the running stack,
a failed job's TTL was 31,108,291 seconds. A user who pasted a key and
hit a rate limit had it sitting in Redis, in plaintext, for 360 days.

So the key never enters the job. It is written once, here, under its own
name with its own short lifetime, encrypted with a key derived from
``SECRET_KEY``; the job carries only the run id; the worker reads it and
deletes it as soon as the run cannot need it again. The TTL is the
guarantee and the delete is a courtesy — whatever else fails, the key
cannot outlive the TTL.

Nothing here touches Mongo. The run document never holds a key, and
there is a test for that too.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from evalbench.config import settings

logger = logging.getLogger("evalbench")

# Long enough for a run to wait in the queue and then execute; short
# enough that a key nobody deleted is gone the same day.
TTL_SECONDS = 6 * 3600

_PREFIX = "evalbench:runkey:"


def name(run_id: str) -> str:
    return f"{_PREFIX}{run_id}"


def _fernet_for(secret: str) -> Fernet:
    # Fernet wants 32 url-safe base64 bytes; SECRET_KEY is arbitrary text.
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return _fernet_for(settings.secret_key)


def stash(redis, run_id: str, key: str) -> None:
    """Hold ``key`` for ``run_id``, encrypted, for at most TTL_SECONDS."""
    redis.set(name(run_id), _fernet().encrypt(key.encode("utf-8")), ex=TTL_SECONDS)


def take(redis, run_id: str) -> str | None:
    """The key for ``run_id``, or None if there is none — or it cannot be
    read, which after a SECRET_KEY rotation is the same thing."""
    raw = redis.get(name(run_id))
    if raw is None:
        return None
    try:
        return _fernet().decrypt(raw).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "Stashed key for run %s could not be decrypted — SECRET_KEY "
            "changed since it was written. Treating as absent.", run_id,
        )
        return None


def discard(redis, run_id: str) -> None:
    redis.delete(name(run_id))
