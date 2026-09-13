"""The benchmarks EvalBench ships, as offered in the workspace.

A curated list rather than "every YAML in suites/", because that
directory also holds demo.yaml (replay-only, needs no key) and CI gates
that make no sense as something a user picks from a dropdown.

"Benchmark" is the word the UI uses; the file format and the API still
say "suite". Same thing — a benchmark is a suite someone else wrote.
"""

from __future__ import annotations

import pathlib
from typing import TypedDict

import yaml

SUITES_DIR = pathlib.Path(__file__).resolve().parents[1] / "suites"


class Benchmark(TypedDict):
    slug: str
    file: str
    title: str
    blurb: str


BUNDLED: list[Benchmark] = [
    {
        "slug": "capability",
        "file": "starter-suite.yaml",
        "title": "General capability",
        "blurb": "Arithmetic, recall, reasoning, definitions, instruction-"
        "following, calibration and safety — reported per category.",
    },
    {
        "slug": "safety",
        "file": "safety.yaml",
        "title": "Safety, both directions",
        "blurb": "Refusal on harmful prompts and over-refusal on benign ones, "
        "across nine categories. Declining a harmless question counts "
        "as a failure.",
    },
    {
        "slug": "rag",
        "file": "rag-demo.yaml",
        "title": "RAG groundedness",
        "blurb": "Did the answer stick to the retrieved source, did the "
        "source contain the answer, and was the retrieval relevant.",
    },
    {
        "slug": "showcase",
        "file": "showcase.yaml",
        "title": "Capability showcase",
        "blurb": "The suite behind the public example report — one answer "
        "judged several ways at once.",
    },
    {
        "slug": "assertions",
        "file": "assertions.yaml",
        "title": "Every check type",
        "blurb": "One small suite that exercises every assertion type, "
        "useful for seeing what each one does.",
    },
]


def load_benchmark(slug: str) -> dict | None:
    """The parsed suite for ``slug``, or None if it isn't bundled."""
    entry = next((b for b in BUNDLED if b["slug"] == slug), None)
    if entry is None:
        return None
    path = SUITES_DIR / entry["file"]
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
                "blurb": b["blurb"],
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
