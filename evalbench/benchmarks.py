"""The benchmarks EvalBench ships, as offered in the workspace.

A curated list rather than "every YAML in suites/", because that
directory also holds demo.yaml (replay-only, needs no key) and CI gates
that make no sense as something a user picks from a dropdown.

"Benchmark" is the word the UI uses; the file format and the API still
say "suite". Same thing — a benchmark is a suite someone else wrote.
"""

from __future__ import annotations

import pathlib
from copy import deepcopy
from functools import cache
from typing import TypedDict

import yaml

from evalbench.answers import suite_needs_judge
from evalbench.db.schemas import TestSuite

SUITES_DIR = pathlib.Path(__file__).resolve().parents[1] / "suites"


class Benchmark(TypedDict):
    slug: str
    file: str
    title: str


BUNDLED: list[Benchmark] = [
    {
        "slug": "capability",
        "file": "starter-suite.yaml",
        "title": "General capability",
    },
    {
        "slug": "safety",
        "file": "safety.yaml",
        "title": "Safety, both directions",
    },
    {
        "slug": "rag",
        "file": "rag-demo.yaml",
        "title": "RAG groundedness",
    },
    {
        "slug": "showcase",
        "file": "showcase.yaml",
        "title": "Capability showcase",
    },
    {
        "slug": "assertions",
        "file": "assertions.yaml",
        "title": "Every check type",
    },
]


@cache
def _parse(slug: str) -> dict | None:
    """Read and parse one bundled suite. Cached for the process.

    These files ship inside the image and cannot change while the process
    runs, but parsing all five cost 50ms — against 9ms for the database
    query on the same endpoint — and being synchronous file I/O in an
    async handler it blocked the event loop for every other request too.
    """
    entry = next((b for b in BUNDLED if b["slug"] == slug), None)
    if entry is None:
        return None
    path = SUITES_DIR / entry["file"]
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_benchmark(slug: str) -> dict | None:
    """The parsed suite for ``slug``, or None if it isn't bundled.

    A deep copy: callers mutate what they get — `adopt` stamps ownership
    onto it — and a shared cache handed out by reference would make one
    request's edit every later request's data.
    """
    parsed = _parse(slug)
    return deepcopy(parsed) if parsed is not None else None


load_benchmark.cache_clear = _parse.cache_clear  # type: ignore[attr-defined]


def describe_benchmarks() -> list[dict]:
    """The list the workspace shows, with live counts read from the files
    so the numbers can't drift from what is actually there."""
    out = []
    for b in BUNDLED:
        data = load_benchmark(b["slug"])
        if data is None:
            continue
        out.append(
            {
                "slug": b["slug"],
                "title": b["title"],
                # what it measures, from the file: one source of truth
                "description": data.get("description", ""),
                # whether scoring supplied answers still needs a grader
                "needs_judge": suite_needs_judge(TestSuite(**data)),
                "name": data.get("name", b["title"]),
                "test_count": len(data.get("tests", [])),
                "provider": data.get("provider", "ollama"),
                "model": data.get("model", ""),
                "categories": sorted(
                    {t.get("category", "general") for t in data.get("tests", [])}
                ),
            }
        )
    return out
