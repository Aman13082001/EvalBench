"""What a benchmark can actually resolve.

The power study (research/REPORT.md) found that a ten-test suite detects
a genuine regression about 21% of the time. That finding is only useful
if it is attached to the benchmarks themselves, so this computes, for one
benchmark, the smallest score drop it could detect at 80% power.

The load-bearing idea: **resolution is an empirical property, not a
property of the YAML.** Two runs of the same benchmark against the same
model do not produce identical scores, and it is the size of that
wobble — not the number of tests — that decides what a comparison can
see. So a benchmark that has never been run twice has no resolution to
report, and says so rather than guessing.
"""

import pytest

from evalbench.core.stats import mde_for_n, samples_for_mde
from evalbench.resolution import resolution_from_runs


def _run(scores: dict[str, float], created_at: str = "2026-09-01"):
    """A run document shaped like the ones Mongo stores."""
    return {
        "created_at": created_at,
        "status": "completed",
        "results": [
            {"test_name": name, "score": s} for name, s in scores.items()
        ],
    }


@pytest.fixture
def as_alice_list(mock_db):
    from fastapi.testclient import TestClient

    from evalbench.api.deps import get_current_user
    from evalbench.api.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "username": "alice", "role": "user", "_id": "a"
    }
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestMdeForN:
    def test_it_inverts_samples_for_mde(self):
        """The two answer the same question from opposite ends; if they
        disagree, one of them is lying to the user."""
        std = 0.2
        n = samples_for_mde(std, mde=0.05)
        # at exactly that n, the detectable effect is back at ~5 points
        assert mde_for_n(n, std) == pytest.approx(0.05, abs=0.002)

    def test_more_tests_resolve_smaller_effects(self):
        std = 0.2
        assert mde_for_n(100, std) < mde_for_n(25, std) < mde_for_n(10, std)

    def test_it_shrinks_with_the_square_root_of_n(self):
        """Quadrupling the suite halves the detectable effect — the fact
        that makes "just add a few more tests" a bad instinct."""
        std = 0.2
        assert mde_for_n(40, std) == pytest.approx(mde_for_n(10, std) / 2, rel=0.01)

    def test_undefined_below_two_tests(self):
        assert mde_for_n(1, 0.2) is None
        assert mde_for_n(0, 0.2) is None

    def test_no_spread_means_no_estimate(self):
        """Zero observed variance would imply infinite precision. From a
        handful of runs that is an artefact, not a finding."""
        assert mde_for_n(20, 0.0) is None


class TestResolutionFromRuns:
    def test_one_run_cannot_measure_resolution(self):
        r = resolution_from_runs([_run({"a": 1.0, "b": 0.0})])
        assert r.mde is None
        assert r.runs_used == 1
        assert "second run" in r.reason

    def test_no_runs_at_all(self):
        r = resolution_from_runs([])
        assert r.mde is None and r.runs_used == 0
        assert "not yet" in r.reason.lower()

    def test_two_runs_give_an_estimate(self):
        a = _run({f"t{i}": 1.0 for i in range(20)}, "2026-09-01")
        wobbled = {f"t{i}": (0.0 if i % 4 == 0 else 1.0) for i in range(20)}
        b = _run(wobbled, "2026-09-02")
        r = resolution_from_runs([a, b])
        assert r.mde is not None and 0 < r.mde < 1
        assert r.runs_used == 2
        assert r.tests == 20
        assert r.reason is None

    def test_tests_are_paired_by_name_not_position(self):
        """A benchmark that gained or lost a test between runs must not
        silently compare unrelated prompts — that would manufacture
        variance and make the suite look blunter than it is."""
        a = _run({"x": 1.0, "y": 0.0, "z": 1.0})
        b = _run({"z": 1.0, "x": 1.0, "y": 0.0}, "2026-09-02")  # reordered
        r = resolution_from_runs([a, b])
        # identical scores once paired correctly: no spread to measure
        assert r.mde is None
        assert "no spread" in r.reason.lower()

    def test_only_tests_present_in_both_runs_are_paired(self):
        a = _run({"x": 1.0, "y": 0.0})
        b = _run({"x": 0.0, "gone": 1.0}, "2026-09-02")
        r = resolution_from_runs([a, b])
        assert r.tests == 1  # only "x" is in both

    def test_more_runs_pool_more_pairs(self):
        runs = [
            _run({f"t{i}": float(i % 2) for i in range(10)}, f"2026-09-0{d}")
            for d in range(1, 5)
        ]
        r = resolution_from_runs(runs)
        assert r.runs_used == 4

    def test_unfinished_runs_are_ignored(self):
        good = _run({"a": 1.0, "b": 0.0})
        bad = {**_run({"a": 0.0, "b": 1.0}), "status": "failed"}
        r = resolution_from_runs([good, bad])
        assert r.runs_used == 1 and r.mde is None

    def test_a_test_that_lost_one_sample_is_still_evidence(self):
        """It carries an error string *and* a score, because another
        sample answered. Reading the error alone as "not scored" is the
        bug that made a 51-test benchmark look unmeasurable."""
        a = {"created_at": "2026-09-01", "status": "completed", "results": [
            {"test_name": "x", "score": 1.0, "runs": 3},
            {"test_name": "y", "score": 1.0, "runs": 2,
             "error": "rate limited", "rate_limited": 1},
        ]}
        b = {"created_at": "2026-09-02", "status": "completed", "results": [
            {"test_name": "x", "score": 0.0, "runs": 3},
            {"test_name": "y", "score": 1.0, "runs": 3},
        ]}
        r = resolution_from_runs([a, b])
        assert r.tests == 2
        assert r.mde is not None

    def test_unscored_tests_do_not_count_as_zero(self):
        """A test that errored has no score. Treating a provider failure
        as a score of 0 would invent variance that the model never
        produced — the same mistake the results view used to make."""
        a = _run({"a": 1.0, "b": 1.0})
        b = {
            "created_at": "2026-09-02",
            "status": "completed",
            "results": [
                {"test_name": "a", "score": 1.0},
                {"test_name": "b", "error": "rate limited", "score": None},
            ],
        }
        r = resolution_from_runs([a, b])
        assert r.tests == 1


# How the list serves this number — stored on the benchmark when a run
# finishes, rather than recomputed per page load — is covered in
# tests/test_stored_resolution.py, along with why the first version was
# wrong at scale.


class TestBundledDescriptionFallback:
    """A copy adopted before descriptions existed still *is* that bundled
    benchmark, so it reads its description from the file rather than
    showing "no description yet" forever. The YAML stays the one source
    of truth; the copy does not have to be migrated."""

    def test_adopted_copy_without_one_falls_back_to_the_file(
        self, as_alice_list, mock_db
    ):
        from bson import ObjectId

        async def suites():
            yield {"_id": ObjectId("507f1f77bcf86cd799439011"), "name": "Old",
                   "created_by": "alice", "test_count": 19,
                   "bundled_slug": "safety"}

        async def none():
            for _ in ():
                yield {}

        mock_db.suites.aggregate.return_value = suites()
        mock_db.test_runs.find.return_value.sort.return_value.limit.return_value = none()

        row = as_alice_list.get("/suites").json()[0]
        assert "over-refusal" in row["description"]

    def test_a_users_own_wording_is_never_overwritten(
        self, as_alice_list, mock_db
    ):
        from bson import ObjectId

        async def suites():
            yield {"_id": ObjectId("507f1f77bcf86cd799439011"), "name": "Mine",
                   "created_by": "alice", "test_count": 19,
                   "bundled_slug": "safety", "description": "My own words."}

        async def none():
            for _ in ():
                yield {}

        mock_db.suites.aggregate.return_value = suites()
        mock_db.test_runs.find.return_value.sort.return_value.limit.return_value = none()

        assert as_alice_list.get("/suites").json()[0]["description"] == "My own words."
