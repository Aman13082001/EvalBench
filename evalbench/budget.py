"""What a run will cost, before it runs.

The server's key is spent in calls — one per generation, one per judged
check — and a free tier meters calls: Groq's headers say 1,000 a day
per model and 8,000 tokens a minute. A budget counted in runs cannot
protect that, because a run is anywhere from 7 calls (the demo suite)
to 228 (the starter suite at three samples): twenty runs of the safety
suite by one person is 1,520 calls, the key's whole day, and everyone
else waits until tomorrow.

So the budget is in calls. Every run declares its cost here, before it
is accepted, and the same number is shown in the workbench before the
click. Three ceilings apply, all in `evalbench/config.py`: per run
(`max_calls_per_run`), per user per day (`daily_call_cap`) and per
instance per day (`daily_call_cap_total`).
"""

from __future__ import annotations

from evalbench.answers import judged_tests
from evalbench.db.schemas import TestSuite


def expected_calls(suite: TestSuite | dict, answers_supplied: bool = False) -> int:
    """Calls a run of ``suite`` will make on a provider.

    ``samples × (tests + judged tests)``: each sample generates one
    answer per test and grades one per judged test. With supplied
    answers nothing is generated, so only the grading counts.

    A stored document is read as-is when it carries ``judged_tests``
    (stamped at import and backfilled at startup); one without it is
    counted the slow way.
    """
    if isinstance(suite, TestSuite):
        samples, tests, judged = suite.samples, len(suite.tests), judged_tests(suite)
    else:
        raw_tests = suite.get("tests") or []
        samples = suite.get("samples") or 1
        tests = len(raw_tests)
        judged = suite.get("judged_tests")
        if judged is None:
            judged = judged_tests(
                TestSuite(
                    name="x",
                    model="x",
                    tests=raw_tests,
                    evaluator=suite.get("evaluator") or "semantic",
                )
            )
    samples = max(1, int(samples))
    return samples * (judged if answers_supplied else tests + judged)
