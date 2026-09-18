"""Bring your own answers: score outputs you already have.

EvalBench scores answers. Until now the only way to get an answer in
front of the checks was to have EvalBench call a model, which locks out
three people: the team with last week's outputs in a CSV, the person
whose model is a notebook with no endpoint, and anyone who will not
paste an API key into a stranger's website. It also makes research
impossible — you cannot separate judge noise from model noise unless you
can score the *same* answers twice.

The replay provider already serves recorded answers. This lets the
caller supply the recording.
"""

import pytest

from evalbench.answers import (
    LLM_ASSERTIONS,
    match_answers,
    parse_answers,
    suite_needs_judge,
)
from evalbench.db.schemas import TestSuite

SUITE = TestSuite(
    name="S", provider="groq", model="m", evaluator="exact",
    tests=[
        {"name": "capital", "prompt": "Capital of France? One word.", "expected": "Paris"},
        {"name": "sum", "prompt": "What is 2+2?", "expected": "4"},
        {"name": "poem", "prompt": "Write a haiku about rain.",
         "assert": [{"type": "llm-rubric", "value": "It is a haiku."}]},
    ],
)


class TestParsing:
    def test_json_array(self):
        rows = parse_answers('[{"test_name": "capital", "response": "Paris"}]')
        assert rows == [{"test_name": "capital", "prompt": None, "response": "Paris"}]

    def test_jsonl(self):
        text = '{"test_name":"capital","response":"Paris"}\n{"test_name":"sum","response":"4"}\n'
        rows = parse_answers(text)
        assert [r["test_name"] for r in rows] == ["capital", "sum"]

    def test_csv(self):
        text = "test_name,response\ncapital,Paris\nsum,4\n"
        rows = parse_answers(text, filename="out.csv")
        assert rows[1] == {"test_name": "sum", "prompt": None, "response": "4"}

    def test_column_names_are_lenient(self):
        """People export from different tools. `answer`, `output`,
        `completion` all mean response; `name`, `test`, `id` all mean the
        test; `input`, `question` mean the prompt."""
        rows = parse_answers('[{"name": "capital", "output": "Paris"}]')
        assert rows[0]["test_name"] == "capital" and rows[0]["response"] == "Paris"
        rows = parse_answers('[{"question": "What is 2+2?", "completion": "4"}]')
        assert rows[0]["prompt"] == "What is 2+2?" and rows[0]["response"] == "4"

    def test_a_row_with_no_response_is_rejected_by_name(self):
        with pytest.raises(ValueError, match="response"):
            parse_answers('[{"test_name": "capital"}]')

    def test_a_row_with_neither_name_nor_prompt_is_rejected(self):
        with pytest.raises(ValueError, match="test_name"):
            parse_answers('[{"response": "Paris"}]')

    def test_garbage_is_rejected_with_a_reason(self):
        with pytest.raises(ValueError):
            parse_answers("this is not any of the three formats")

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError, match="No answers"):
            parse_answers("")


class TestMatching:
    def test_by_test_name(self):
        recordings, missing = match_answers(SUITE, [
            {"test_name": "capital", "prompt": None, "response": "Paris"},
            {"test_name": "sum", "prompt": None, "response": "4"},
            {"test_name": "poem", "prompt": None, "response": "rain falls / on the roof / softly"},
        ])
        assert missing == []
        assert len(recordings) == 3

    def test_by_prompt_when_there_is_no_name(self):
        """Whitespace-insensitive, like the replay provider itself: YAML
        folding re-wraps lines and must not break the match."""
        recordings, missing = match_answers(SUITE, [
            {"test_name": None, "prompt": "Capital of France?\n  One word.", "response": "Paris"},
        ])
        assert "capital" not in missing
        assert missing == ["sum", "poem"]

    def test_the_recording_is_keyed_so_the_replay_provider_finds_it(self):
        from evalbench.core.providers.replay import ReplayProvider, _normalize

        recordings, _ = match_answers(SUITE, [
            {"test_name": "capital", "prompt": None, "response": "Paris"},
        ])
        assert _normalize("Capital of France? One word.") in recordings
        # and it round-trips through the provider that will serve it
        import asyncio

        p = ReplayProvider(recordings=recordings)
        r = asyncio.run(p.generate("m", "Capital of France? One word."))
        assert r.text == "Paris"

    def test_missing_tests_are_named(self):
        _, missing = match_answers(SUITE, [
            {"test_name": "capital", "prompt": None, "response": "Paris"},
        ])
        assert missing == ["sum", "poem"]

    def test_an_answer_for_an_unknown_test_is_reported_not_dropped(self):
        """Silently ignoring it hides a typo in the file; the caller should
        hear that "capitol" matched nothing."""
        with pytest.raises(ValueError, match="capitol"):
            match_answers(SUITE, [
                {"test_name": "capitol", "prompt": None, "response": "Paris"},
            ])

    def test_nothing_matching_is_an_error(self):
        with pytest.raises(ValueError, match="match"):
            match_answers(SUITE, [
                {"test_name": None, "prompt": "something else entirely", "response": "x"},
            ])


class TestWhoGrades:
    def test_a_deterministic_suite_needs_no_judge(self):
        s = TestSuite(name="S", model="m", evaluator="exact",
                      tests=[{"name": "a", "prompt": "p", "expected": "e"}])
        assert suite_needs_judge(s) is False

    def test_a_judge_evaluator_needs_one(self):
        s = TestSuite(name="S", model="m", evaluator="judge",
                      tests=[{"name": "a", "prompt": "p", "expected": "e"}])
        assert suite_needs_judge(s) is True

    def test_a_per_test_override_counts(self):
        s = TestSuite(name="S", model="m", evaluator="exact",
                      tests=[{"name": "a", "prompt": "p", "expected": "e",
                              "evaluator": "security"}])
        assert suite_needs_judge(s) is True

    def test_llm_assertions_count(self):
        assert suite_needs_judge(SUITE) is True  # the haiku rubric
        assert {"judge", "llm-rubric", "faithfulness",
                "context-recall", "context-precision"} <= LLM_ASSERTIONS

    def test_semantic_does_not_need_a_judge(self):
        """Cosine similarity over local sentence embeddings. No key, no
        network — it must not be the reason a keyless run is refused."""
        s = TestSuite(name="S", model="m", evaluator="semantic",
                      tests=[{"name": "a", "prompt": "p", "expected": "e"}])
        assert suite_needs_judge(s) is False


class TestTheCli:
    def test_answers_flag_posts_them_and_labels_the_run(self, tmp_path, monkeypatch):
        """`evalbench run suite.yaml --answers out.jsonl`: the file is read
        and validated locally first, then posted with the run so the
        server replays it. A bad file fails before any request."""
        from typer.testing import CliRunner

        from evalbench import cli

        suite = tmp_path / "s.yaml"
        suite.write_text(
            "name: S\nmodel: m\nevaluator: exact\ntests:\n"
            "  - name: capital\n    prompt: Capital of France?\n    expected: Paris\n",
            encoding="utf-8",
        )
        answers = tmp_path / "v2.jsonl"
        answers.write_text('{"test_name": "capital", "response": "Paris"}\n', encoding="utf-8")

        posted = {}

        class _Resp:
            status_code = 201

            def raise_for_status(self):
                pass

            def json(self):
                return {"id": "507f1f77bcf86cd799439011", "created": True}

        def fake_post(url, **kw):
            posted[url.rsplit("/", 1)[-1]] = kw.get("json")
            return _Resp()

        monkeypatch.setattr(cli.httpx, "post", fake_post)
        monkeypatch.setattr(cli, "_get_headers", lambda *_: {})
        monkeypatch.setattr(
            cli, "_run_and_wait",
            lambda sid, headers, model, body=None: posted.update(run=body) or "run-1",
        )
        monkeypatch.setattr(cli, "_fetch_summary", lambda *_: (_ for _ in ()).throw(SystemExit(0)), raising=False)

        r = CliRunner().invoke(cli.app, ["run", str(suite), "--answers", str(answers)])
        body = posted.get("run")
        assert body is not None, r.output
        assert body["answers"][0]["response"] == "Paris"
        assert body["model"] == "v2"  # the file's name labels the run

    def test_a_bad_answers_file_fails_before_any_request(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from evalbench import cli

        suite = tmp_path / "s.yaml"
        suite.write_text(
            "name: S\nmodel: m\nevaluator: exact\ntests:\n"
            "  - name: capital\n    prompt: Capital of France?\n    expected: Paris\n",
            encoding="utf-8",
        )
        bad = tmp_path / "bad.jsonl"
        bad.write_text('{"test_name": "capitol", "response": "Paris"}\n', encoding="utf-8")

        calls = []
        monkeypatch.setattr(cli.httpx, "post", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(cli, "_get_headers", lambda *_: {})

        r = CliRunner().invoke(cli.app, ["run", str(suite), "--answers", str(bad)])
        assert r.exit_code == 1
        assert "capitol" in r.output
