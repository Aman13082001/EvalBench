"""Bring your own answers: score outputs you already have.

EvalBench scores answers. Every check — the string match, the judge, the
faithfulness decomposition, the safety verdict — reads the answer and
nothing else. Calling a model is only how an answer usually arrives.

Until now it was the only way, which locked out three kinds of people:
the team with last week's outputs in a CSV, the person whose model is a
notebook with no endpoint, and anyone who will not paste an API key into
a stranger's website. It also made a whole class of research impossible:
you cannot separate judge noise from model noise unless you can score the
*same* answers more than once.

The replay provider already serves recorded answers. This module turns a
caller's file into that recording, and says what — if anything — still
needs a model: only the checks that ask an LLM to grade.
"""

from __future__ import annotations

import csv
import io
import json

from evalbench.core.providers.replay import _normalize
from evalbench.db.schemas import TestSuite

# Assertion types that ask an LLM to grade. Everything else — string
# checks, regex, JSON schema, latency, cost, and semantic similarity (local
# sentence embeddings) — scores without any model at all.
LLM_ASSERTIONS = frozenset(
    {"judge", "llm-rubric", "faithfulness", "context-recall", "context-precision"}
)
LLM_EVALUATORS = frozenset({"judge", "security"})

# People export from different tools, and nobody agrees on a column name.
_RESPONSE_KEYS = ("response", "answer", "output", "completion", "text")
_NAME_KEYS = ("test_name", "test", "name", "id")
_PROMPT_KEYS = ("prompt", "input", "question")


def _first(row: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return None


def _rows_from(text: str, filename: str) -> list[dict]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("No answers found — the file is empty.")

    # JSON array first: it is unambiguous.
    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array of objects.")
        return [d for d in data if isinstance(d, dict)]

    # JSONL: every non-blank line is an object.
    if stripped.startswith("{"):
        rows = []
        for n, line in enumerate(stripped.splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Line {n} is not valid JSON: {e.msg}") from e
        return rows

    # CSV: a header row naming the columns.
    if filename.lower().endswith((".csv", ".tsv")) or "," in stripped.splitlines()[0]:
        dialect = "excel-tab" if filename.lower().endswith(".tsv") else "excel"
        reader = csv.DictReader(io.StringIO(stripped), dialect=dialect)
        return [dict(r) for r in reader]

    raise ValueError(
        "Could not read this as JSON, JSON Lines or CSV. Each answer needs "
        "a `response` and either a `test_name` or a `prompt`."
    )


def parse_answers(text: str, filename: str = "") -> list[dict]:
    """Normalise a caller's file to ``[{test_name, prompt, response}]``.

    Accepts a JSON array, JSON Lines, or CSV with a header. Column names
    are lenient (see the key lists above). Every row must carry a
    response and at least one of a test name or a prompt.
    """
    rows = _rows_from(text, filename)
    if not rows:
        raise ValueError("No answers found in the file.")

    out = []
    for n, row in enumerate(rows, 1):
        response = _first(row, _RESPONSE_KEYS)
        if response is None:
            raise ValueError(
                f"Answer {n} has no response (looked for one of "
                f"{', '.join(_RESPONSE_KEYS)})."
            )
        name = _first(row, _NAME_KEYS)
        prompt = _first(row, _PROMPT_KEYS)
        if name is None and prompt is None:
            raise ValueError(
                f"Answer {n} has neither a test_name nor a prompt, so there "
                "is no way to tell which test it answers."
            )
        out.append({"test_name": name, "prompt": prompt, "response": response})
    return out


def match_answers(
    suite: TestSuite | dict, answers: list[dict], label: str = "your answers"
) -> tuple[dict[str, dict], list[str]]:
    """Pair answers with the suite's tests.

    Returns the recording the replay provider serves — keyed the way it
    looks prompts up, whitespace-insensitively — and the names of tests
    that got no answer. Those still run; they simply never get an answer,
    which the results report as such rather than as a failure.

    An answer that matches nothing is an error, not a silent drop: it is
    almost always a typo in the file, and the caller should hear "capitol
    matched no test" rather than wonder why one test never answered.
    """
    tests = suite.tests if isinstance(suite, TestSuite) else suite.get("tests", [])
    by_name = {}
    by_prompt = {}
    for t in tests:
        name = t.name if hasattr(t, "name") else t["name"]
        prompt = t.prompt if hasattr(t, "prompt") else t["prompt"]
        by_name[name] = prompt
        by_prompt[_normalize(prompt)] = prompt

    recordings: dict[str, dict] = {}
    unmatched: list[str] = []
    for a in answers:
        prompt = None
        if a.get("test_name") and a["test_name"] in by_name:
            prompt = by_name[a["test_name"]]
        elif a.get("prompt") and _normalize(a["prompt"]) in by_prompt:
            prompt = by_prompt[_normalize(a["prompt"])]
        if prompt is None:
            unmatched.append(a.get("test_name") or (a.get("prompt") or "")[:40])
            continue
        recordings[_normalize(prompt)] = {
            "prompt": prompt,
            "response": a["response"],
            "model": label,
        }

    if unmatched:
        raise ValueError(
            f"{len(unmatched)} answer(s) matched no test in this benchmark: "
            f"{', '.join(repr(u) for u in unmatched[:5])}"
            + (" …" if len(unmatched) > 5 else "")
        )
    if not recordings:
        raise ValueError("None of the answers match a test in this benchmark.")

    missing = [
        name for name, prompt in by_name.items()
        if _normalize(prompt) not in recordings
    ]
    return recordings, missing


def suite_needs_judge(suite: TestSuite) -> bool:
    """Whether any check in the suite asks an LLM to grade.

    This is what decides if a bring-your-own-answers run needs a key at
    all. A suite of string, regex, schema and semantic checks scores with
    zero model calls; one with a rubric needs a grader, and only for the
    grading.
    """
    for t in suite.tests:
        if t.assert_:
            if any(a.type in LLM_ASSERTIONS for a in t.assert_):
                return True
        elif (t.evaluator or suite.evaluator) in LLM_EVALUATORS:
            return True
    return False
