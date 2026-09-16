"""Losing samples to a rate limit is a quality loss, and must read as one.

A real run of the 51-test starter suite at `samples: 3` lost 34 of its
153 generations to 429s. No test was lost — every one was answered at
least once — so the summary said `errors: 0` and the page announced
"0 of 51 tests never got an answer", which is not a sentence, while the
actual cost went unmentioned.

That cost is real. `samples: 3` exists so a pass/fail is a majority vote
rather than one draw; a test scored on one sample instead of three is
back to a coin flip, which widens its interval and blunts the
benchmark's resolution. So the summary counts undersampled tests, and
the provider coordinates its backoff instead of letting four workers
burn their retries against the same ceiling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evalbench.api.summary import summarize_run


def _r(runs: int, rate_limited: int = 0, passed: bool = True):
    return {"test_name": f"t{runs}{rate_limited}", "passed": passed,
            "score": 1.0 if passed else 0.0, "runs": runs,
            "rate_limited": rate_limited, "latency_ms": 10}


class TestUndersampling:
    def test_it_counts_tests_that_lost_samples(self):
        doc = {"samples": 3, "results": [_r(3), _r(2, 1), _r(1, 2)]}
        s = summarize_run(doc)
        assert s["samples_requested"] == 3
        assert s["undersampled_tests"] == 2

    def test_a_clean_run_reports_none(self):
        s = summarize_run({"samples": 3, "results": [_r(3), _r(3)]})
        assert s["undersampled_tests"] == 0

    def test_older_runs_infer_the_request_from_the_best_test(self):
        """Runs stored before the field existed still have to read
        honestly: the tests that got every sample reveal the intent."""
        s = summarize_run({"results": [_r(3), _r(1, 2)]})
        assert s["samples_requested"] == 3
        assert s["undersampled_tests"] == 1

    def test_single_sample_suites_cannot_be_undersampled(self):
        s = summarize_run({"samples": 1, "results": [_r(1), _r(1)]})
        assert s["undersampled_tests"] == 0

    def test_a_test_that_never_answered_is_not_called_undersampled(self):
        """It is already counted as an error; counting it twice would
        double-report the same failure."""
        doc = {"samples": 3,
               "results": [_r(3), {"test_name": "x", "error": "boom",
                                   "runs": 0, "rate_limited": 3}]}
        s = summarize_run(doc)
        assert s["errors"] == 1
        assert s["undersampled_tests"] == 0


class TestCoordinatedBackoff:
    """When the ceiling is per-minute and shared, one worker hitting it
    means every worker is about to. Pausing the provider is what turns
    four independent retry storms into one wait."""

    @pytest.fixture
    def provider(self):
        from evalbench.core.providers.openai_compat import (
            OpenAICompatibleProvider,
        )

        p = OpenAICompatibleProvider("http://x", "k", name="groq")
        p._client = MagicMock()
        return p

    @pytest.mark.asyncio
    async def test_a_429_pauses_the_whole_provider(self, provider):
        limited = MagicMock(status_code=429, headers={"retry-after": "7"})
        ok = MagicMock(status_code=200)
        ok.raise_for_status = MagicMock()
        provider._client.post = AsyncMock(side_effect=[limited, ok])

        slept = []
        with patch("asyncio.sleep", AsyncMock(side_effect=slept.append)):
            await provider._post_with_retry({})

        assert 7 in slept
        assert provider.paused_for() > 0

    @pytest.mark.asyncio
    async def test_a_later_caller_waits_out_the_pause(self, provider):
        ok = MagicMock(status_code=200)
        ok.raise_for_status = MagicMock()
        provider._client.post = AsyncMock(return_value=ok)
        provider._pause_for(5.0)

        slept = []
        with patch("asyncio.sleep", AsyncMock(side_effect=slept.append)):
            await provider._post_with_retry({})

        # it waited before spending a request against a known-closed door
        assert slept and slept[0] > 0

    @pytest.mark.asyncio
    async def test_no_pause_means_no_waiting(self, provider):
        ok = MagicMock(status_code=200)
        ok.raise_for_status = MagicMock()
        provider._client.post = AsyncMock(return_value=ok)

        slept = []
        with patch("asyncio.sleep", AsyncMock(side_effect=slept.append)):
            await provider._post_with_retry({})
        assert slept == []

    @pytest.mark.asyncio
    async def test_it_gives_up_eventually_rather_than_hanging(self, provider):
        from evalbench.core.providers.base import RateLimitError

        limited = MagicMock(status_code=429, headers={})
        provider._client.post = AsyncMock(return_value=limited)

        with patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(RateLimitError):
                await provider._post_with_retry({})
