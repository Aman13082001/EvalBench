"""PR-comment rendering, target resolution, and upsert."""

import json
from unittest.mock import MagicMock, patch

import pytest

from evalbench.ci.pr_comment import (
    MARKER,
    render_markdown,
    resolve_target,
    upsert_comment,
)

REPORT = {
    "suite": "CI Gate",
    "run_id": "abc123",
    "summary": {
        "model": "openai/gpt-oss-20b",
        "total_tests": 6,
        "passed": 5,
        "failed": 1,
        "errors": 0,
        "pass_rate": 0.8333,
        "avg_score": 0.87,
        "avg_latency_ms": 540,
        "total_cost_usd": 0.0003,
        "total_prompt_tokens": 400,
        "total_completion_tokens": 250,
        "by_category": {
            "arithmetic": {"total": 2, "pass_rate": 1.0, "avg_score": 1.0},
            "safety": {"total": 1, "pass_rate": 0.0, "avg_score": 0.0},
        },
        "assertion_types": {
            "icontains": {"passed": 4, "failed": 0},
            "latency": {"passed": 1, "failed": 1},
        },
    },
    "regression": None,
    "gate": {"fail_under": 0.8, "passed": True, "regression_detected": False},
}


class TestRenderMarkdown:
    def test_contains_marker_and_verdict(self):
        md = render_markdown(REPORT)
        assert md.startswith(MARKER)
        assert "passed" in md
        assert "openai/gpt-oss-20b" in md
        assert "83.3%" in md  # pass rate

    def test_failed_gate_shows_cross(self):
        r = json.loads(json.dumps(REPORT))
        r["gate"]["passed"] = False
        md = render_markdown(r)
        assert "❌" in md

    def test_regression_block_lists_regressed_tests(self):
        r = json.loads(json.dumps(REPORT))
        r["regression"] = {
            "regression_detected": True,
            "baseline_mean": 0.9,
            "current_mean": 0.7,
            "p_value": 0.01,
            "per_test": [
                {"test_name": "t1", "baseline_score": 0.9,
                 "current_score": 0.2, "delta": -0.7, "regressed": True},
                {"test_name": "t2", "baseline_score": 0.9,
                 "current_score": 0.9, "delta": 0.0, "regressed": False},
            ],
        }
        md = render_markdown(r)
        assert "Regression vs baseline" in md
        assert "| t1 |" in md
        assert "| t2 |" not in md

    def test_no_baseline_no_regression_block(self):
        md = render_markdown(REPORT)
        assert "Regression vs baseline" not in md


class TestResolveTarget:
    def test_explicit_args_win(self):
        assert resolve_target("me/repo", 7) == ("me/repo", 7)

    def test_from_github_ref(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
        monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        assert resolve_target() == ("me/repo", 42)

    def test_from_event_file(self, monkeypatch, tmp_path):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 99}}))
        monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
        monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        assert resolve_target() == ("me/repo", 99)

    def test_raises_when_unresolvable(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_REF", raising=False)
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        with pytest.raises(ValueError, match="Could not resolve"):
            resolve_target()


class TestUpsertComment:
    def _client(self, existing_comments):
        client = MagicMock()
        list_resp = MagicMock()
        list_resp.json.return_value = existing_comments
        list_resp.raise_for_status.return_value = None
        client.get.return_value = list_resp

        write_resp = MagicMock()
        write_resp.json.return_value = {"html_url": "https://x/comment"}
        write_resp.raise_for_status.return_value = None
        client.post.return_value = write_resp
        client.patch.return_value = write_resp

        ctx = MagicMock()
        ctx.__enter__.return_value = client
        ctx.__exit__.return_value = False
        return ctx, client

    def test_creates_when_no_marker_comment(self):
        ctx, client = self._client([{"id": 1, "body": "unrelated"}])
        with patch("evalbench.ci.pr_comment.httpx.Client", return_value=ctx):
            action, url = upsert_comment("me/repo", 5, "tok", "body")
        assert action == "created"
        client.post.assert_called_once()
        client.patch.assert_not_called()

    def test_updates_existing_marker_comment(self):
        ctx, client = self._client(
            [{"id": 7, "body": f"{MARKER}\nold report"}]
        )
        with patch("evalbench.ci.pr_comment.httpx.Client", return_value=ctx):
            action, url = upsert_comment("me/repo", 5, "tok", "new body")
        assert action == "updated"
        client.patch.assert_called_once()
        client.post.assert_not_called()
