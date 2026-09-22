"""What a run costs, in the unit the key is spent in.

A free tier meters calls: Groq's headers say 1,000 a day per model and
8,000 tokens a minute. A budget counted in runs cannot protect that,
because a run is anywhere from 7 calls (the demo) to 228 (the starter
suite at three samples) — twenty runs of the safety suite by one person
is 1,520 calls, the key's whole day, and everyone else waits until
tomorrow. So the budget is in calls, and every run declares its cost
before it is accepted.
"""

import pathlib

import yaml

from evalbench.benchmarks import describe_benchmarks
from evalbench.budget import expected_calls
from evalbench.config import Settings
from evalbench.db.schemas import TestSuite


def _bundled(name: str) -> TestSuite:
    data = yaml.safe_load(pathlib.Path("suites", name).read_text(encoding="utf-8"))
    return TestSuite(**data)


class TestExpectedCalls:
    def test_one_generation_per_test_per_sample_plus_one_judge_per_judged_test(self):
        """safety.yaml: 19 tests, all judged, 2 samples → 2 × (19 + 19)."""
        assert expected_calls(_bundled("safety.yaml")) == 76

    def test_the_starter_suite_is_the_expensive_one(self):
        assert expected_calls(_bundled("starter-suite.yaml")) == 228

    def test_the_demo_is_cheap(self):
        assert expected_calls(_bundled("demo.yaml")) == 10

    def test_supplied_answers_cost_only_the_grading(self):
        """Nothing is generated; only the judged checks call a model."""
        assert expected_calls(_bundled("safety.yaml"), answers_supplied=True) == 38
        assert expected_calls(_bundled("research-power.yaml"), answers_supplied=True) == 0

    def test_a_stored_document_works_without_reparsing_when_it_carries_the_count(self):
        """The suite list has thousands of tests across documents; it uses
        the `judged_tests` stored at import rather than rebuilding each
        suite. The two paths must agree."""
        s = _bundled("safety.yaml")
        doc = {"tests": [t.model_dump(by_alias=True) for t in s.tests], "samples": 2, "judged_tests": 19}
        assert expected_calls(doc) == expected_calls(s) == 76

    def test_a_stored_document_without_the_count_is_counted(self):
        s = _bundled("demo.yaml")
        doc = {"tests": [t.model_dump(by_alias=True) for t in s.tests], "evaluator": s.evaluator}
        assert expected_calls(doc) == 10

    def test_samples_below_one_count_as_one(self):
        s = TestSuite(name="S", model="m", samples=1, tests=[{"name": "t", "prompt": "p", "expected": "e"}])
        assert expected_calls({"tests": [{"name": "t", "prompt": "p"}], "samples": 0}) == 1
        assert expected_calls(s) == 1


class TestTheShippedCeilings:
    """A ceiling nobody can run under is not a budget, it is a closed door.

    The visitor who has just found this instance presses the biggest
    benchmark first. If its cost does not fit both the per-run ceiling
    and one person's day, the button is dead for everyone who has not
    brought a key — and the only thing measured is their patience.
    """

    @staticmethod
    def _default(name: str) -> int:
        return Settings.model_fields[name].default

    def test_the_biggest_bundled_benchmark_fits_one_run(self):
        biggest = max(b["calls"] for b in describe_benchmarks())
        assert biggest <= self._default("max_calls_per_run")

    def test_it_also_fits_inside_one_persons_day(self):
        """The per-run ceiling is not the binding one on its own: a 228
        call run still dies against a 150 call day."""
        biggest = max(b["calls"] for b in describe_benchmarks())
        assert biggest <= self._default("daily_call_cap")

    def test_the_instance_still_fits_inside_the_free_tier(self):
        """Groq's free tier is 1,000 requests a day per model. Whatever
        one person may spend, everyone together stays under it."""
        assert self._default("daily_call_cap_total") <= 1000

    def test_one_person_cannot_take_the_whole_instance_day(self):
        """At least three full-sized runs must fit in a day, or the first
        visitor closes the instance for the rest."""
        assert self._default("daily_call_cap") * 3 <= self._default("daily_call_cap_total")
