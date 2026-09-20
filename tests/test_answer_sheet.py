"""The question sheet: the prompts, handed out in the shape the answers
come back in.

"Bring your own answers" accepted a file of `{test_name, response}` rows
but never gave anyone the questions. To evaluate a model EvalBench cannot
call — a notebook, an internal gateway, last week's outputs — someone had
to copy test names off the benchmark page and hope the prompt they ran
was byte-for-byte the one the runner sends. The sheet closes that: every
prompt exactly as `TestRunner` would send it, one row per test, with an
empty `response` to fill in. The same file, filled, is the upload.
"""

import csv
import io
import json

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.answers import answer_sheet, match_answers, parse_answers
from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.db.schemas import TestSuite

SUITE = TestSuite(
    name="S", provider="groq", model="m", evaluator="exact",
    tests=[
        {"name": "capital", "prompt": "Capital of France? One word.", "expected": "Paris"},
        {"name": "sum", "prompt": "What is 2+2?", "expected": "4"},
        # A grounded test: the prompt has newlines, quotes and a comma —
        # everything a CSV writer can get wrong.
        {"name": "grounded", "prompt": 'Context:\n"The Nile is 6,650 km long."\n\nHow long is the Nile?',
         "expected": "6,650 km", "context": ["The Nile is 6,650 km long."]},
    ],
)


def _fill(text: str, fmt: str) -> str:
    """What a person does with the sheet: put an answer in every row."""
    if fmt == "jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        for r in rows:
            r["response"] = f"answer to {r['test_name']}"
        return "\n".join(json.dumps(r) for r in rows) + "\n"
    rows = list(csv.DictReader(io.StringIO(text)))
    for r in rows:
        r["response"] = f"answer to {r['test_name']}"
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["test_name", "prompt", "response"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


class TestTheSheet:
    @pytest.mark.parametrize("fmt", ["csv", "jsonl"])
    def test_filled_in_it_matches_every_test(self, fmt):
        """The one property that matters: the sheet, filled, is a valid
        upload that covers the whole benchmark — nothing unmatched,
        nothing missing — through the same parser the upload uses."""
        sheet = answer_sheet(SUITE, fmt)
        filled = _fill(sheet, fmt)
        rows = parse_answers(filled, f"sheet.{fmt}")
        recordings, missing = match_answers(SUITE, rows)
        assert missing == []
        assert len(recordings) == len(SUITE.tests)

    @pytest.mark.parametrize("fmt", ["csv", "jsonl"])
    def test_the_prompt_is_exactly_what_the_runner_sends(self, fmt):
        """Newlines, quotes and commas survive the trip. If they did not,
        the model under test would answer a different question than the
        one EvalBench's own runs ask."""
        sheet = answer_sheet(SUITE, fmt)
        if fmt == "jsonl":
            rows = [json.loads(line) for line in sheet.splitlines() if line.strip()]
        else:
            rows = list(csv.DictReader(io.StringIO(sheet)))
        assert [r["prompt"] for r in rows] == [t.prompt for t in SUITE.tests]
        assert [r["test_name"] for r in rows] == [t.name for t in SUITE.tests]
        assert all(r["response"] == "" for r in rows)

    def test_expected_answers_are_not_on_the_sheet(self):
        """The sheet goes to the model under test. Sending it the answers
        would be contamination, not evaluation."""
        for fmt in ("csv", "jsonl"):
            assert "Paris" not in answer_sheet(SUITE, fmt)
            assert "expected" not in answer_sheet(SUITE, fmt)

    def test_an_unknown_format_is_refused(self):
        with pytest.raises(ValueError, match="csv or jsonl"):
            answer_sheet(SUITE, "xlsx")


SUITE_ID = "507f1f77bcf86cd799439011"
ALICE = {"username": "alice", "role": "user", "_id": "a"}
DOC = {
    "_id": ObjectId(SUITE_ID), "name": "Alice's suite", "provider": "groq",
    "model": "m", "evaluator": "exact", "created_by": "alice",
    "tests": [t.model_dump(by_alias=True) for t in SUITE.tests],
}


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestTheRoutes:
    def test_my_suite_downloads_as_a_file(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(DOC)
        r = as_alice.get(f"/suites/{SUITE_ID}/answer-sheet?format=csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert 'filename="alices-suite-answers.csv"' in r.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert [x["test_name"] for x in rows] == ["capital", "sum", "grounded"]

    def test_jsonl_is_the_default(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(DOC)
        r = as_alice.get(f"/suites/{SUITE_ID}/answer-sheet")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        assert json.loads(r.text.splitlines()[0])["test_name"] == "capital"

    def test_someone_elses_suite_is_not_handed_out(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = {**DOC, "created_by": "bob"}
        r = as_alice.get(f"/suites/{SUITE_ID}/answer-sheet")
        assert r.status_code in (403, 404)

    def test_a_bundled_benchmark_needs_no_copy_first(self, as_alice, mock_db):
        """The workbench offers bundled benchmarks before anyone adopts
        one. Downloading the questions must not create a suite."""
        r = as_alice.get("/suites/bundled/capability/answer-sheet?format=csv")
        assert r.status_code == 200
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert rows and all(x["response"] == "" for x in rows)
        mock_db.suites.insert_one.assert_not_called()

    def test_a_bundled_slug_that_does_not_exist(self, as_alice):
        r = as_alice.get("/suites/bundled/nope/answer-sheet")
        assert r.status_code == 404

    def test_a_bad_format_is_a_400(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(DOC)
        r = as_alice.get(f"/suites/{SUITE_ID}/answer-sheet?format=xlsx")
        assert r.status_code == 400


class TestTheCli:
    def test_writes_the_sheet_for_a_suite_file(self, tmp_path):
        """`evalbench answer-sheet suite.yaml -o sheet.csv`, then the
        filled sheet is what `evalbench run --answers sheet.csv` takes."""
        from typer.testing import CliRunner

        from evalbench import cli

        suite = tmp_path / "s.yaml"
        suite.write_text(
            "name: S\nmodel: m\nevaluator: exact\ntests:\n"
            "  - name: capital\n    prompt: Capital of France?\n    expected: Paris\n"
            "  - name: sum\n    prompt: What is 2+2?\n    expected: '4'\n",
            encoding="utf-8",
        )
        out = tmp_path / "sheet.csv"
        r = CliRunner().invoke(cli.app, ["answer-sheet", str(suite), "-o", str(out)])
        assert r.exit_code == 0, r.output
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert [x["test_name"] for x in rows] == ["capital", "sum"]
        assert "2 tests" in r.output
        assert "--answers" in r.output

    def test_prints_jsonl_to_stdout_without_a_file(self, tmp_path):
        from typer.testing import CliRunner

        from evalbench import cli

        suite = tmp_path / "s.yaml"
        suite.write_text(
            "name: S\nmodel: m\nevaluator: exact\ntests:\n"
            "  - name: capital\n    prompt: Capital of France?\n    expected: Paris\n",
            encoding="utf-8",
        )
        r = CliRunner().invoke(cli.app, ["answer-sheet", str(suite), "--format", "jsonl"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output.strip().splitlines()[0]) == {
            "test_name": "capital", "prompt": "Capital of France?", "response": "",
        }
