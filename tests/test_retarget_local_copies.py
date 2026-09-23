"""Adopted copies made before a bundled benchmark named its provider.

`suites/starter-suite.yaml` used to name no provider, so it inherited
the schema default — ``ollama``. Every copy anyone adopted carries that
default in the database, and fixing the YAML does not reach them: they
are documents now, not files. On an instance with no Ollama, pressing
"Run benchmark" on such a copy is refused, and the benchmark page shows
`ollama / llama3.1` under a benchmark that is meant to run anywhere.

So the copies are brought back in line with the benchmark they are
copies *of* — and only those. A suite somebody wrote themselves may
mean ollama exactly, and is not ours to rewrite.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from evalbench.api import main as main_module


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


@pytest.fixture
def suites(mock_db):
    def _set(docs):
        mock_db.suites.find.return_value = _Cursor(docs)
        mock_db.suites.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    return _set


class TestCopiesOfBundledBenchmarksFollowTheBenchmark:
    @pytest.mark.asyncio
    async def test_an_adopted_copy_is_retargeted(self, mock_db, suites):
        suites([{
            "_id": ObjectId(), "bundled_slug": "capability",
            "provider": "ollama", "model": "llama3.1",
        }])
        n = await main_module._retarget_bundled_copies()
        assert n == 1
        fields = mock_db.suites.update_one.call_args[0][1]["$set"]
        assert fields["provider"] == "groq"
        assert fields["model"] and fields["model"] != "llama3.1"

    @pytest.mark.asyncio
    async def test_a_suite_of_your_own_is_left_alone(self, mock_db, suites):
        """No bundled_slug: somebody wrote this, and may own an Ollama."""
        suites([{
            "_id": ObjectId(), "provider": "ollama", "model": "llama3.1",
        }])
        assert await main_module._retarget_bundled_copies() == 0
        mock_db.suites.update_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_copy_of_a_benchmark_that_really_is_local_is_left_alone(
        self, mock_db, suites
    ):
        """If the bundled definition itself says ollama, the copy agrees
        with it and there is nothing to fix."""
        suites([{
            "_id": ObjectId(), "bundled_slug": "capability",
            "provider": "ollama", "model": "llama3.1",
        }])
        with patch.object(
            main_module, "load_benchmark", return_value={"provider": "ollama", "model": "llama3.1"}
        ):
            assert await main_module._retarget_bundled_copies() == 0
        mock_db.suites.update_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_unknown_slug_is_left_alone(self, mock_db, suites):
        suites([{
            "_id": ObjectId(), "bundled_slug": "no-such-benchmark",
            "provider": "ollama", "model": "llama3.1",
        }])
        assert await main_module._retarget_bundled_copies() == 0
        mock_db.suites.update_one.assert_not_called()
