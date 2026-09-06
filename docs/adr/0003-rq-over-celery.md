# 3. RQ over Celery, and inline by default

**Status:** accepted · **Date:** 2026-09

## Context

Suite runs are long (seconds to minutes) and must not block the HTTP
request. The API needed a job model. But EvalBench also has to stay
trivially runnable — `pip install`, a CI job, and a GitHub Action all need
to work without standing up a broker.

## Decision

Two backends behind one `submit_run()` call, chosen by `JOB_BACKEND`:

- `inline` (default) — FastAPI `BackgroundTasks`, no broker.
- `rq` — enqueue to Redis, executed by `python -m evalbench.worker`.

The Docker stack sets `rq`; everything else defaults to `inline`.

## Rationale

**Why not Celery.** Celery brings a configuration surface (result
backends, serializers, routing, beat) far larger than "run this function
later". RQ is a few hundred lines of concept, uses the Redis already in
the stack, and its failure modes are legible.

**Why keep an inline path at all.** Requiring Redis to run one eval suite
would make the CLI and the GitHub Action worse for no benefit. The
inline path keeps the zero-dependency story intact; the queue is opt-in
for when durability and horizontal scale actually matter.

## Consequences

- Two code paths to keep working. Kept small: both call the same
  `execute_run_job(run_id, suite_id)`, which loads everything it needs
  from the database rather than taking objects as arguments.
- The RQ worker creates a fresh Mongo client per job, because motor binds
  to the event loop and each job runs under its own `asyncio.run`.
- A crashed worker leaves a run marked `running`. Handled by the startup
  reaper, which fails any non-terminal run on boot.
