"""Indexes for the queries the app actually runs.

Three hot paths were doing collection scans. `GET /suites` matches on
`created_by` and sorts by `created_at`; the recent-runs list does the
same on runs; and `runs_used_today()` counts a user's server-key runs on
*every single run submission* — the quota check, on the hot path, with
no index to use.

This test names the queries rather than the indexes, so it fails when a
query is added that nothing supports.
"""

from unittest.mock import AsyncMock, patch

import pytest

from evalbench.api.main import app


def _created(mock_db, collection):
    """The index specs created on one collection, as comparable keys."""
    out = []
    for call in getattr(mock_db, collection).create_index.call_args_list:
        spec = call[0][0]
        out.append(tuple(spec) if isinstance(spec, list) else ((spec, 1),))
    return out


@pytest.fixture
async def indexed(mock_db):
    from evalbench.api import main

    mock_db.users.create_index = AsyncMock()
    with patch.object(main, "db", mock_db), patch.object(
        main.settings, "job_backend", "inline"
    ):
        async with main.lifespan(app):
            pass
    return mock_db


class TestSuiteQueries:
    @pytest.mark.asyncio
    async def test_the_benchmark_list_has_an_index(self, indexed):
        """`{"created_by": me}` sorted by created_at. Without this the
        page scans every suite of every user, on every load."""
        assert (("created_by", 1), ("created_at", -1)) in _created(
            indexed, "suites"
        )


class TestRunQueries:
    @pytest.mark.asyncio
    async def test_recent_runs_and_the_quota_count_have_an_index(self, indexed):
        """Serves both `GET /runs` (mine, newest first) and the daily cap
        count, which runs before every single submission."""
        assert (("created_by", 1), ("created_at", -1)) in _created(
            indexed, "test_runs"
        )

    @pytest.mark.asyncio
    async def test_the_existing_ones_survive(self, indexed):
        specs = _created(indexed, "test_runs")
        assert (("suite_id", 1), ("created_at", -1)) in specs
        assert (("status", 1),) in specs
