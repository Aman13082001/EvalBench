"""The judge-variance study, attached to every judged benchmark.

`research/judge-variance/REPORT.md` measured what a judge adds to a
score: per answer, re-asking the same judge moves it by about 0.055 and
different judges disagree by about 0.078 (0-1 scale). Left as a report
that is a fact someone might read once. Attached to a benchmark as the
floor under its resolution, it is the number that says whether a small
drop was the model or the grader.
"""

import json
import pathlib

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench import resolution
from evalbench.answers import judged_tests, suite_needs_judge
from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.db.schemas import TestSuite

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALICE = {"username": "alice", "role": "user", "_id": "a"}


def _suite(**kw) -> TestSuite:
    return TestSuite(**{"name": "S", "model": "m", "tests": [], **kw})


class TestCountingJudgedTests:
    def test_a_rubric_assertion_is_judged(self):
        s = _suite(tests=[
            {"name": "a", "prompt": "p", "assert": [{"type": "llm-rubric", "criteria": "x"}]},
            {"name": "b", "prompt": "p", "expected": "e"},
        ])
        assert judged_tests(s) == 1
        assert suite_needs_judge(s) is True

    def test_the_judge_evaluator_is_judged(self):
        s = _suite(evaluator="judge", tests=[
            {"name": "a", "prompt": "p", "expected": "e"},
            {"name": "b", "prompt": "p", "expected": "e", "evaluator": "exact"},
        ])
        assert judged_tests(s) == 1

    def test_a_deterministic_suite_has_none(self):
        s = _suite(evaluator="exact", tests=[{"name": "a", "prompt": "p", "expected": "e"}])
        assert judged_tests(s) == 0
        assert suite_needs_judge(s) is False


class TestTheFloor:
    def test_no_judged_tests_no_floor(self):
        assert resolution.judge_floor(0, 10) is None
        assert resolution.judge_floor(None, 10) is None

    def test_an_all_judged_benchmark_scales_with_root_n(self):
        f = resolution.judge_floor(16, 16)
        assert f.rerun == pytest.approx(resolution.JUDGE_RETEST_SD / 4, abs=1e-4)
        assert f.switch == pytest.approx(
            (resolution.JUDGE_OFFSET_SD ** 2 + resolution.JUDGE_INTERACTION_SD ** 2 / 16) ** 0.5,
            abs=1e-4,
        )
        assert f.judged == 16 and f.tests == 16

    def test_a_partly_judged_benchmark_dilutes_the_floor(self):
        """Four judged tests in sixteen: judge noise lands on a quarter of
        the mean, so the floor is sd*sqrt(4)/16, not sd/sqrt(4)."""
        f = resolution.judge_floor(4, 16)
        assert f.rerun == pytest.approx(resolution.JUDGE_RETEST_SD * 2 / 16, abs=1e-4)
        assert f.rerun < resolution.judge_floor(16, 16).rerun

    def test_the_constants_are_the_study_not_a_memory_of_it(self):
        """Re-run `analyze` and the numbers may move; this fails until the
        constants are updated to match, with the date."""
        path = ROOT / "research" / "judge-variance" / "study.json"
        if not path.exists():
            pytest.skip("study not present")
        s = json.loads(path.read_text(encoding="utf-8"))
        assert resolution.JUDGE_RETEST_SD == s["components"]["sd"]["retest"]
        assert resolution.JUDGE_INTERACTION_SD == s["components"]["sd"]["answer_x_judge"]
        assert resolution.JUDGE_OFFSET_SD == s["components"]["sd"]["judge"]
        assert resolution.JUDGE_STUDY_DATE == s["generated"]


class TestItReachesTheBenchmarkList:
    @pytest.fixture
    def as_alice(self, mock_db):
        app.dependency_overrides[get_current_user] = lambda: ALICE
        with TestClient(app) as c:
            yield c
        from tests.conftest import override_get_current_user

        app.dependency_overrides[get_current_user] = override_get_current_user

    def test_bundled_benchmarks_carry_their_floor(self):
        """Every bundled benchmark has at least one judged check, so every
        one carries a floor — and a benchmark where the judge touches half
        the tests has a lower floor than one where it touches them all."""
        from evalbench.benchmarks import describe_benchmarks

        by_slug = {b["slug"]: b for b in describe_benchmarks()}
        assert all(b["judge_floor"]["rerun"] > 0 for b in by_slug.values())
        half = by_slug["capability"]   # 25 of 51 judged
        whole = by_slug["safety"]      # 19 of 19 judged
        assert half["judged_tests"] < half["test_count"]
        assert whole["judged_tests"] == whole["test_count"]
        assert half["judge_floor"]["rerun"] < whole["judge_floor"]["rerun"]

    def test_a_stored_count_becomes_a_floor_on_the_list(self, as_alice, mock_db):
        async def agg(pipeline):
            for d in [
                {"_id": ObjectId(), "name": "judged", "test_count": 9, "judged_tests": 9,
                 "created_by": "alice"},
                {"_id": ObjectId(), "name": "plain", "test_count": 9, "judged_tests": 0,
                 "created_by": "alice"},
                # stored before the count existed, but it is a copy of a
                # bundled benchmark whose file can be counted
                {"_id": ObjectId(), "name": "old copy", "test_count": 3,
                 "bundled_slug": "assertions", "created_by": "alice"},
                {"_id": ObjectId(), "name": "unknown", "test_count": 3, "created_by": "alice"},
            ]:
                yield d

        mock_db.suites.aggregate = agg
        rows = {s["name"]: s for s in as_alice.get("/suites").json()}
        assert rows["judged"]["judge_floor"]["judged"] == 9
        assert rows["plain"]["judge_floor"] is None
        assert rows["old copy"]["judge_floor"] is not None
        assert rows["unknown"]["judge_floor"] is None

    def test_import_and_adopt_store_the_count(self, as_alice, mock_db):
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId()
        as_alice.post("/suites/import", json={
            "name": "S", "model": "m",
            "tests": [{"name": "a", "prompt": "p", "assert": [{"type": "llm-rubric", "criteria": "x"}]},
                      {"name": "b", "prompt": "p", "expected": "e"}],
        })
        doc = mock_db.suites.insert_one.call_args[0][0]
        assert doc["judged_tests"] == 1
        assert doc["needs_judge"] is True


class TestOldSuitesGetTheCountOnStartup:
    """`judged_tests` was added after suites already existed. A suite
    stored without it would show no floor for ever — honest, but wrong
    in the way a missed migration is wrong. Startup counts it once."""

    @pytest.mark.asyncio
    async def test_startup_backfills_suites_that_lack_the_count(self, mock_db):
        from unittest.mock import AsyncMock, patch

        from evalbench.api import main

        old = {
            "_id": ObjectId(), "name": "old", "evaluator": "exact",
            "tests": [
                {"name": "a", "prompt": "p", "assert": [{"type": "llm-rubric", "criteria": "x"}]},
                {"name": "b", "prompt": "p", "expected": "e"},
                {"name": "c", "prompt": "p", "expected": "e", "evaluator": "judge"},
            ],
        }

        async def find(query, projection=None):
            assert "judged_tests" in query  # only the ones lacking it
            yield old

        mock_db.suites.find = find
        mock_db.suites.update_one = AsyncMock()
        mock_db.users.create_index = AsyncMock()
        with patch.object(main, "db", mock_db), patch.object(
            main.settings, "job_backend", "inline"
        ):
            async with main.lifespan(app):
                pass

        sets = [c.args[1]["$set"] for c in mock_db.suites.update_one.call_args_list
                if c.args[0] == {"_id": old["_id"]}]
        assert sets == [{"judged_tests": 2, "needs_judge": True}]


class TestOldRunsGetAStatusOnStartup:
    """Runs from before the job model have results but no `status`. Every
    list that asks for completed runs — history, resolution, the admin
    count — skips them, and the admin page files them under 'unknown'.
    They finished; the field did not exist yet. Startup says so, once."""

    @pytest.mark.asyncio
    async def test_startup_marks_statusless_runs_with_results_completed(self, mock_db):
        from unittest.mock import AsyncMock, patch

        from evalbench.api import main

        finished = {"_id": ObjectId(), "results": [{"test_name": "a", "score": 1.0}] * 3}
        empty = {"_id": ObjectId(), "results": []}

        async def find(query, projection=None):
            assert query.get("status") is None and "status" in query
            for d in (finished, empty):
                yield d

        async def suites_find(query, projection=None):
            return
            yield  # pragma: no cover

        mock_db.test_runs.find = find
        mock_db.suites.find = suites_find
        mock_db.test_runs.update_one = AsyncMock()
        mock_db.users.create_index = AsyncMock()
        with patch.object(main, "db", mock_db), patch.object(
            main.settings, "job_backend", "inline"
        ):
            async with main.lifespan(app):
                pass

        calls = {c.args[0]["_id"]: c.args[1]["$set"] for c in mock_db.test_runs.update_one.call_args_list
                 if "_id" in c.args[0]}
        assert calls[finished["_id"]]["status"] == "completed"
        assert calls[finished["_id"]]["completed_tests"] == 3
        assert calls[finished["_id"]]["total_tests"] == 3
        assert calls[finished["_id"]]["progress"] == 1.0
        # nothing scored, nothing known: leave it alone rather than guess
        assert empty["_id"] not in calls
