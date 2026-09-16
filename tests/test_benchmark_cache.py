"""The bundled manifest is read from disk once, not per request.

`describe_benchmarks()` parses five YAML files — 50ms, measured in the
container, against 9ms for the database query on the same endpoint. It
ran on every call to `GET /suites` and `GET /suites/bundled`, and being
synchronous file I/O inside an async handler it blocked the event loop
for the whole 50ms, so it throttled every other request too. One uvicorn
worker meant the entire API was capped by a YAML parse.

These files ship inside the image and cannot change while the process is
running, so the right number of reads is one.
"""

import pytest

from evalbench import benchmarks


@pytest.fixture(autouse=True)
def fresh_cache():
    benchmarks.load_benchmark.cache_clear()
    yield
    benchmarks.load_benchmark.cache_clear()


def test_repeated_calls_do_not_reread_the_files(monkeypatch):
    reads = []
    real = benchmarks.pathlib.Path.read_text

    def counted(self, *a, **k):
        reads.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(benchmarks.pathlib.Path, "read_text", counted)

    first = benchmarks.describe_benchmarks()
    after_first = len(reads)
    for _ in range(25):
        benchmarks.describe_benchmarks()

    assert after_first > 0, "the first call must actually read them"
    assert len(reads) == after_first, "later calls re-read the files"
    assert benchmarks.describe_benchmarks() == first


def test_the_content_is_still_right():
    listed = {d["slug"]: d for d in benchmarks.describe_benchmarks()}
    for b in benchmarks.BUNDLED:
        assert listed[b["slug"]]["test_count"] == len(
            benchmarks.load_benchmark(b["slug"])["tests"]
        )


def test_a_cached_suite_cannot_be_mutated_by_a_caller():
    """A shared cache handed out by reference lets one request's edit
    become every later request's data — including the adopt endpoint,
    which stamps its own fields onto what it is given."""
    a = benchmarks.load_benchmark("safety")
    a["name"] = "tampered"
    assert benchmarks.load_benchmark("safety")["name"] != "tampered"
