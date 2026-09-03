"""Render an EvalBench run report as Markdown and upsert it as a PR comment.

The comment carries a hidden marker so re-runs update the same comment
instead of piling up new ones.
"""

from __future__ import annotations

import json
import os
import re

import httpx

MARKER = "<!-- evalbench-report -->"
GITHUB_API = "https://api.github.com"


def _pct(x: float | None) -> str:
    return f"{(x or 0) * 100:.1f}%"


def render_markdown(report: dict) -> str:
    """Build the PR comment body from a `run --report` JSON dict."""

    summary = report.get("summary", {})
    gate = report.get("gate", {})
    comp = report.get("regression")

    passed = gate.get("passed", False)
    verdict = "✅ **passed**" if passed else "❌ **failed**"

    lines = [
        MARKER,
        f"## EvalBench — {report.get('suite', 'run')} {verdict}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Model | `{summary.get('model', '?')}` |",
        f"| Tests | {summary.get('total_tests', 0)} "
        f"({summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed"
        + (f", {summary['errors']} errored" if summary.get("errors") else "")
        + ") |",
        f"| Pass rate | {_pct(summary.get('pass_rate'))} "
        f"(gate ≥ {_pct(gate.get('fail_under'))}) |",
        f"| Avg score | {summary.get('avg_score', 0):.3f} |",
        f"| Avg latency | {summary.get('avg_latency_ms', 0):.0f} ms |",
    ]

    cost = summary.get("total_cost_usd") or 0
    if cost:
        lines.append(f"| Est. cost | ${cost:.4f} |")
    tin = summary.get("total_prompt_tokens")
    tout = summary.get("total_completion_tokens")
    if tin or tout:
        lines.append(f"| Tokens (in / out) | {tin} / {tout} |")

    by_cat = summary.get("by_category") or {}
    if len(by_cat) > 1:
        lines += ["", "<details><summary>By category</summary>", "",
                  "| Category | Tests | Pass rate | Avg score |",
                  "|---|---|---|---|"]
        for name, s in sorted(by_cat.items()):
            lines.append(
                f"| {name} | {s.get('total', 0)} | "
                f"{_pct(s.get('pass_rate'))} | {s.get('avg_score', 0):.3f} |"
            )
        lines += ["", "</details>"]

    a_types = summary.get("assertion_types") or {}
    if a_types:
        parts = [
            f"{t}: {c.get('passed', 0)}✓"
            + (f" / {c['failed']}✗" if c.get("failed") else "")
            for t, c in sorted(a_types.items())
        ]
        lines += ["", "**Assertions:** " + " · ".join(parts)]

    if comp:
        if comp.get("regression_detected"):
            lines += ["", f"### ⚠️ Regression vs baseline "
                      f"(mean {comp.get('baseline_mean')} → "
                      f"{comp.get('current_mean')}, p={comp.get('p_value')})"]
        else:
            lines += ["", f"_No regression vs baseline "
                      f"(Δ {comp.get('mean_diff')}, p={comp.get('p_value')})._"]
        regressed = [t for t in comp.get("per_test", []) if t.get("regressed")]
        if regressed:
            lines += ["", "| Regressed test | Baseline | Current | Δ |",
                      "|---|---|---|---|"]
            for t in regressed:
                lines.append(
                    f"| {t['test_name']} | {t['baseline_score']:.3f} | "
                    f"{t['current_score']:.3f} | {t['delta']:+.3f} |"
                )

    run_id = report.get("run_id")
    if run_id:
        lines += ["", f"<sub>run `{run_id}`</sub>"]

    return "\n".join(lines)


def resolve_target(
    repo: str | None = None,
    pr: int | None = None,
) -> tuple[str, int]:
    """Fill repo / PR number from GitHub Actions env when not passed."""

    repo = repo or os.getenv("GITHUB_REPOSITORY")

    if pr is None:
        ref = os.getenv("GITHUB_REF", "")
        m = re.match(r"refs/pull/(\d+)/", ref)
        if m:
            pr = int(m.group(1))

    if pr is None:
        event_path = os.getenv("GITHUB_EVENT_PATH")
        if event_path and os.path.exists(event_path):
            with open(event_path) as f:
                event = json.load(f)
            num = (event.get("pull_request") or event.get("issue") or {}).get(
                "number"
            )
            if num:
                pr = int(num)

    if not repo or pr is None:
        raise ValueError(
            "Could not resolve repo/PR. Pass --repo owner/name and --pr N, "
            "or run inside a GitHub Actions pull_request job."
        )
    return repo, pr


def upsert_comment(
    repo: str, pr: int, token: str, body: str
) -> tuple[str, str]:
    """Create or update the marker comment. Returns (action, html_url)."""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(base_url=GITHUB_API, headers=headers, timeout=20.0) as c:
        existing = None
        r = c.get(f"/repos/{repo}/issues/{pr}/comments?per_page=100")
        r.raise_for_status()
        for comment in r.json():
            if MARKER in (comment.get("body") or ""):
                existing = comment["id"]
                break

        if existing:
            r = c.patch(
                f"/repos/{repo}/issues/comments/{existing}",
                json={"body": body},
            )
            r.raise_for_status()
            return "updated", r.json()["html_url"]

        r = c.post(
            f"/repos/{repo}/issues/{pr}/comments", json={"body": body}
        )
        r.raise_for_status()
        return "created", r.json()["html_url"]
