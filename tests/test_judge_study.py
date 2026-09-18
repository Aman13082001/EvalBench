"""The judge-variance study's arithmetic, proven on data with known answers.

A study script that spends 900 real calls and then reports a variance
decomposition is only worth running if the decomposition recovers
components it is fed. So: simulate answers × judges × repeats with
chosen effect sizes, run the real `decompose`, check it finds them.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study():
    spec = importlib.util.spec_from_file_location(
        "run_study_judge", ROOT / "scripts" / "run_study_judge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_study_judge"] = mod
    spec.loader.exec_module(mod)
    return mod


def _simulate(seed, a=60, j=3, k=5, sd_a=0.20, sd_j=0.05, sd_aj=0.06, sd_e=0.03):
    rng = random.Random(seed)
    answers = [("strong" if i < a // 2 else "weak", f"t{i}") for i in range(a)]
    judges = [f"j{n}" for n in range(j)]
    ea = {x: rng.gauss(0, sd_a) for x in answers}
    ej = {y: rng.gauss(0, sd_j) for y in judges}
    eaj = {(x, y): rng.gauss(0, sd_aj) for x in answers for y in judges}
    cells = {
        (x, y): [0.6 + ea[x] + ej[y] + eaj[(x, y)] + rng.gauss(0, sd_e) for _ in range(k)]
        for x in answers
        for y in judges
    }
    return cells, answers, judges


class TestTheDecomposition:
    def test_it_recovers_known_components(self, study):
        """Fed sd_a=0.20, sd_j=0.05, sd_aj=0.06, sd_e=0.03, it must find
        them — within the sampling error of 60 answers and 3 judges."""
        cells, answers, judges = _simulate(seed=1)
        d = study.decompose(cells, answers, judges)
        assert abs(d["sd"]["answer"] - 0.20) < 0.04
        assert abs(d["sd"]["answer_x_judge"] - 0.06) < 0.02
        assert abs(d["sd"]["retest"] - 0.03) < 0.005
        # three judges is a tiny sample for the judge term; only its
        # order of magnitude is checkable
        assert d["sd"]["judge"] < 0.15
        assert abs(sum(d["share"].values()) - 1.0) < 1e-3  # shares are rounded to 4 dp

    def test_the_retest_term_is_exact_when_there_is_no_retest_noise(self, study):
        cells, answers, judges = _simulate(seed=2, sd_e=0.0)
        d = study.decompose(cells, answers, judges)
        assert d["variance"]["retest"] == 0.0
        assert d["share"]["retest"] == 0.0

    def test_a_judge_offset_lands_in_the_judge_term_not_the_interaction(self, study):
        """One judge scores everything 0.2 higher. That is a constant
        offset — harmless within the judge, fatal across a switch — and
        it must be reported as such, not smeared into answer×judge."""
        cells, answers, judges = _simulate(seed=3, sd_j=0.0, sd_aj=0.0, sd_e=0.0)
        for x in answers:
            cells[(x, judges[0])] = [s + 0.2 for s in cells[(x, judges[0])]]
        d = study.decompose(cells, answers, judges)
        assert d["sd"]["judge"] > 0.08
        assert d["sd"]["answer_x_judge"] < 1e-6
        assert d["judge_means"][judges[0]] > d["judge_means"][judges[1]] + 0.19

    def test_identical_scores_everywhere_do_not_crash(self, study):
        cells, answers, judges = _simulate(seed=4, sd_a=0, sd_j=0, sd_aj=0, sd_e=0)
        d = study.decompose(cells, answers, judges)
        assert all(v == 0.0 for v in d["variance"].values())

    def test_a_cell_short_one_repeat_is_tolerated(self, study):
        cells, answers, judges = _simulate(seed=5)
        cells[(answers[0], judges[0])].pop()
        d = study.decompose(cells, answers, judges)
        assert 4.9 < d["repeats_harmonic"] < 5.0
        assert abs(d["sd"]["retest"] - 0.03) < 0.005


class TestTheParseClassifier:
    """A reply the production parser could not read comes back as 3/5.
    That is not a judgement; it must be kept out of the variance."""

    @pytest.mark.parametrize(
        "raw, kind",
        [
            ('{"score": 4, "reason": "fine"}', "json"),
            ('Sure.\n```json\n{"score": 2, "reason": "x"}\n```', "json"),
            ("SCORE: 3\nREASON: ok", "score-line"),
            ("I'd give this a 4 out of 5.", "digit"),
            ("I cannot evaluate this.", "fallback"),
            ("", "fallback"),
        ],
    )
    def test_it_names_how_the_reply_was_read(self, study, raw, kind):
        assert study._classify(raw) == kind


class TestScoringIsResumable:
    @pytest.mark.asyncio
    async def test_a_second_pass_scores_only_what_is_missing(self, study, tmp_path, monkeypatch):
        monkeypatch.setattr(study, "OUT", tmp_path)
        monkeypatch.setattr(study, "JUDGES", ["j/a", "j/b"])
        suite = study._suite()
        for which in ("strong", "weak"):
            with (tmp_path / f"answers-{which}.jsonl").open("w", encoding="utf-8") as f:
                for t in suite.tests[:3]:
                    f.write(json.dumps({"test_name": t.name, "category": t.category,
                                        "prompt": t.prompt, "response": f"{which} answer"}) + "\n")

        calls = []

        class _Resp:
            def __init__(self, text):
                self.text = text

        class _Judge:
            def __init__(self, fail_once):
                self.fail_once = fail_once
                self.seen = 0

            async def generate(self, model, prompt, temperature=0.7):
                self.seen += 1
                calls.append(model)
                if self.fail_once and self.seen == 1:
                    raise RuntimeError("429 pretend")
                return _Resp('{"score": 4, "reason": "ok"}')

            async def close(self):
                pass

        judges = {"j/a": _Judge(fail_once=True), "j/b": _Judge(fail_once=False)}
        monkeypatch.setattr(study, "get_provider", lambda name: judges.pop(next(iter(judges))) if judges else _Judge(False))
        # first pass: 3 tests × 2 sets × 2 judges × 1 repeat = 12, one fails
        await study.score(repeats=1, only_judge=None)
        rows = study._read_jsonl(tmp_path / "scores.jsonl")
        assert len(rows) == 12
        assert sum(1 for r in rows if r["error"]) == 1
        assert all(r["parsed"] == "json" and r["score"] == 0.8 for r in rows if not r["error"])

        # second pass: exactly the one missing cell
        calls.clear()
        await study.score(repeats=1, only_judge=None)
        assert len(calls) == 1
        rows = study._read_jsonl(tmp_path / "scores.jsonl")
        assert sum(1 for r in rows if not r["error"]) == 12
