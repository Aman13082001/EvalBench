"""`evalbench merge-suites` — fold duplicate suites into one per name.

Before import became create-or-update, every `evalbench run` inserted a
new suite; one database reached 70 suites with 18 names. The repair has
two halves: a pure planner the operator sees before anything is written,
and an apply step whose one rule is that runs are never deleted — they
are re-pointed at the surviving copy.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from evalbench.maintenance import MergeGroup, apply_merge, plan_merge

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _s(_id, name, owner="admin", *, baseline=None, days=0):
    return {"_id": _id, "name": name, "created_by": owner,
            "baseline_run_id": baseline, "created_at": T0 + timedelta(days=days)}


class TestPlan:
    def test_keeps_the_newest_when_nothing_distinguishes_them(self):
        plan = plan_merge([_s(1, "A", days=0), _s(2, "A", days=2), _s(3, "A", days=1)])
        assert len(plan) == 1
        assert plan[0].keep == 2 and sorted(plan[0].drop) == [1, 3]

    def test_a_baseline_beats_recency(self):
        """A baseline is the one deliberate act on a suite; the copy
        holding it is the one the person cared about."""
        plan = plan_merge([_s(1, "A", baseline="r", days=0), _s(2, "A", days=5)])
        assert plan[0].keep == 1 and plan[0].drop == [2]

    def test_same_name_different_owner_is_not_a_duplicate(self):
        plan = plan_merge([_s(1, "A", "alice"), _s(2, "A", "bob")])
        assert plan == []

    def test_singletons_are_left_alone(self):
        assert plan_merge([_s(1, "A"), _s(2, "B")]) == []

    def test_claim_folds_orphans_into_the_claimers_group(self):
        """Suites from before accounts existed have no owner. Claimed for
        admin, they merge with admin's same-name suite and the survivor
        is admin's — so they stop being ghosts only an admin can see."""
        plan = plan_merge(
            [_s(1, "A", None, days=0), _s(2, "A", "admin", days=1), _s(3, "B", None)],
            claim="admin",
        )
        by_name = {g.name: g for g in plan}
        assert by_name["A"].owner == "admin" and by_name["A"].keep == 2
        # a lone orphan is still a group: it needs its owner written
        assert by_name["B"].owner == "admin" and by_name["B"].drop == []

    def test_without_claim_orphans_merge_among_themselves(self):
        plan = plan_merge([_s(1, "A", None), _s(2, "A", None)])
        assert len(plan) == 1 and plan[0].owner is None


class TestApply:
    @pytest.mark.asyncio
    async def test_runs_are_repointed_before_suites_are_deleted(self):
        db = MagicMock()
        db.test_runs.update_many = AsyncMock(return_value=MagicMock(modified_count=7))
        db.suites.delete_many = AsyncMock(return_value=MagicMock(deleted_count=2))
        db.suites.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
        order = []
        db.test_runs.update_many.side_effect = lambda *a, **k: order.append("move") or MagicMock(modified_count=7)
        db.suites.delete_many.side_effect = lambda *a, **k: order.append("delete") or MagicMock(deleted_count=2)

        out = await apply_merge(db, [MergeGroup("admin", "A", keep=9, drop=[1, 2])])

        assert order == ["move", "delete"]
        filt, update = db.test_runs.update_many.call_args[0]
        assert filt == {"suite_id": {"$in": ["1", "2"]}}
        assert update == {"$set": {"suite_id": "9"}}
        assert db.suites.delete_many.call_args[0][0] == {"_id": {"$in": [1, 2]}}
        assert out == {"moved_runs": 7, "deleted_suites": 2, "claimed": 0}
        # nothing ever deletes a run
        assert not hasattr(db.test_runs, "delete_many") or not db.test_runs.delete_many.called

    @pytest.mark.asyncio
    async def test_claiming_writes_the_owner_onto_the_keeper(self):
        db = MagicMock()
        db.test_runs.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
        db.suites.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
        db.suites.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        out = await apply_merge(db, [MergeGroup("admin", "B", keep=3, drop=[])])
        filt, update = db.suites.update_one.call_args[0]
        assert filt["_id"] == 3 and update["$set"]["created_by"] == "admin"
        assert out["claimed"] == 1
        db.suites.delete_many.assert_not_called()


class TestCommand:
    def test_dry_run_by_default_writes_nothing(self, monkeypatch):
        from evalbench import cli

        suites = [_s(1, "A"), _s(2, "A")]

        class _Cursor:
            def __aiter__(self):
                async def gen():
                    for s in suites:
                        yield s
                return gen()

        db = MagicMock()
        db.suites.find = MagicMock(return_value=_Cursor())
        db.test_runs.count_documents = AsyncMock(return_value=3)
        client = MagicMock()
        client.__getitem__ = MagicMock(return_value=db)
        client.close = MagicMock()
        monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", lambda *_a, **_k: client)

        applied = []

        async def fake_apply(_db, groups):
            applied.append(groups)
            return {"moved_runs": 0, "deleted_suites": 0, "claimed": 0}

        monkeypatch.setattr("evalbench.maintenance.apply_merge", fake_apply)

        r = CliRunner().invoke(cli.app, ["merge-suites"])
        assert r.exit_code == 0, r.output
        assert "A" in r.output and "dry run" in r.output.lower()
        assert applied == []

        r = CliRunner().invoke(cli.app, ["merge-suites", "--apply"])
        assert r.exit_code == 0, r.output
        assert len(applied) == 1 and applied[0][0].name == "A"
