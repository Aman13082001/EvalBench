import json
import os
import sys
import time
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from evalbench.config import settings
from evalbench.explain import (
    explain_assertion,
    explain_comparison,
    explain_run,
)

# Legacy Windows consoles default to cp1252 and choke on the ✓/⚠ glyphs
# Rich emits. Force UTF-8 (with a safe fallback) so the CLI never crashes
# on output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

app = typer.Typer(help="EvalBench — Local LLM Evaluation CLI")
console = Console()
API_URL = os.getenv("EVALBENCH_API_URL", "http://localhost:8000")

AUTH_FILE = Path.home() / ".evalbench" / "auth.json"


def _load_auth():
    if AUTH_FILE.exists():
        return json.loads(AUTH_FILE.read_text())
    return {}


def _save_auth(data):
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data))


def _get_headers(api_key: str | None = None):
    headers = {}

    if api_key:
        headers["X-API-Key"] = api_key
        return headers

    auth = _load_auth()

    if auth.get("token"):
        headers["Authorization"] = f"Bearer {auth['token']}"
    elif auth.get("api_key"):
        headers["X-API-Key"] = auth["api_key"]

    return headers


def _run_and_wait(
    suite_id: str, headers: dict, model: str, body: dict | None = None
) -> str:
    """Kick off an async run and poll until it finishes. Returns the run id."""

    r = httpx.post(
        f"{API_URL}/suites/{suite_id}/run",
        headers=headers,
        json=body,
        timeout=30.0,
    )
    if r.status_code == 400:
        console.print(f"[red]{r.json().get('detail', r.text)}[/red]")
        raise typer.Exit(code=1)
    r.raise_for_status()
    body = r.json()
    run_id = body["run_id"]
    total = body.get("test_count") or 0

    deadline = time.monotonic() + float(settings.suite_run_timeout)

    with Progress(
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.completed}/{task.total} tests"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Running {model}", total=total or None)

        while True:
            s = httpx.get(
                f"{API_URL}/runs/{run_id}/status",
                headers=headers,
                timeout=30.0,
            )
            s.raise_for_status()
            info = s.json()
            state = info.get("status", "completed")
            done = info.get("completed_tests", 0)
            tot = info.get("total_tests") or total

            if tot:
                progress.update(task, completed=done, total=tot)

            if state == "failed":
                progress.stop()
                console.print(
                    f"[bold red]✗ Run failed:[/bold red] "
                    f"{info.get('error') or 'unknown error'}"
                )
                raise typer.Exit(code=1)

            if state == "completed":
                progress.update(
                    task, completed=tot or done, total=tot or done or 1
                )
                return run_id

            if time.monotonic() > deadline:
                progress.stop()
                console.print(
                    "[bold red]✗ Timed out waiting for the run "
                    "to finish.[/bold red]"
                )
                raise typer.Exit(code=1)

            time.sleep(1.0)


def _check_regression(
    baseline_id: str, current_id: str, headers: dict
) -> dict | None:
    """Run the baseline comparison and print it. Returns the comparison dict."""

    r = httpx.post(
        f"{API_URL}/regression",
        json={"baseline_run_id": baseline_id, "current_run_id": current_id},
        headers=headers,
        timeout=20.0,
    )
    if r.status_code >= 400:
        console.print(
            f"[yellow]Baseline check skipped: {r.text[:200]}[/yellow]"
        )
        return None

    comp = r.json()

    table = Table(title="Baseline Comparison")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("Baseline mean", str(comp.get("baseline_mean")))
    table.add_row("Current mean", str(comp.get("current_mean")))
    table.add_row("Mean diff", str(comp.get("mean_diff")))
    table.add_row("P-value (paired t)", str(comp.get("p_value")))
    if comp.get("effect_size") is not None:
        table.add_row("Effect size (d)", str(comp["effect_size"]))
    mc = comp.get("mcnemar")
    if mc:
        table.add_row(
            "McNemar",
            f"{mc['regressions']} regressed / {mc['fixes']} fixed, "
            f"p={mc['p_value']}",
        )
    if comp.get("min_samples_for_5pt_mde"):
        table.add_row(
            "Samples for 5pt MDE", str(comp["min_samples_for_5pt_mde"])
        )
    console.print(table)

    regressed_tests = [
        t for t in comp.get("per_test", []) if t.get("regressed")
    ]
    if regressed_tests:
        rt = Table(title="Regressed Tests")
        rt.add_column("Test", style="cyan")
        rt.add_column("Baseline", style="magenta")
        rt.add_column("Current", style="magenta")
        rt.add_column("Δ", style="red")
        for t in regressed_tests:
            rt.add_row(
                t["test_name"],
                f"{t['baseline_score']:.3f}",
                f"{t['current_score']:.3f}",
                f"{t['delta']:+.3f}",
            )
        console.print(rt)

    console.print(f"[dim]{explain_comparison(comp)}[/dim]\n")

    if comp.get("regression_detected"):
        console.print("[bold red]✗ REGRESSION DETECTED vs baseline[/bold red]")
    else:
        console.print("[bold green]✓ No regression vs baseline[/bold green]")

    return comp


# ═══════════════════════════════════════════════════════════════
# AUTH COMMANDS
# ═══════════════════════════════════════════════════════════════


@app.command()
def login(
    username: str = typer.Option(..., "--username", "-u"),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
    ),
):
    """Authenticate and store JWT token."""
    r = httpx.post(
        f"{API_URL}/auth/login",
        data={"username": username, "password": password},
        timeout=10.0,
    )

    if r.status_code == 401:
        console.print(
            "[bold red]✗[/bold red] Invalid username or password"
        )
        raise typer.Exit(code=1)

    r.raise_for_status()

    token = r.json()["access_token"]
    _save_auth({"token": token})

    console.print(
        f"[bold green]✓[/bold green] Logged in as "
        f"[cyan]{username}[/cyan]"
    )


@app.command()
def logout():
    """Clear stored credentials."""
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()

    console.print("[bold green]✓[/bold green] Logged out")


@app.command()
def whoami():
    """Show current authenticated user."""
    auth = _load_auth()

    if not auth:
        console.print("[yellow]Not logged in[/yellow]")
        return

    headers = _get_headers()

    r = httpx.get(
        f"{API_URL}/auth/me",
        headers=headers,
        timeout=10.0,
    )

    if r.status_code == 401:
        console.print(
            "[red]Session expired. Please login again.[/red]"
        )
        return

    r.raise_for_status()

    data = r.json()

    console.print(
        f"User: [cyan]{data['username']}[/cyan]"
    )
    console.print(
        f"Role: [cyan]{data['role']}[/cyan]"
    )


@app.command()
def register(
    username: str = typer.Option(..., "--username", "-u"),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
    ),
):
    """Register a new account."""
    r = httpx.post(
        f"{API_URL}/auth/register",
        json={"username": username, "password": password},
        timeout=10.0,
    )

    if r.status_code == 400:
        console.print(
            f"[bold red]✗[/bold red] {r.json()['detail']}"
        )
        raise typer.Exit(code=1)

    r.raise_for_status()

    data = r.json()

    _save_auth({"api_key": data["api_key"]})

    console.print(
        f"[bold green]✓[/bold green] Registered as "
        f"[cyan]{username}[/cyan]"
    )

    console.print(
        f"API Key saved: [cyan]{data['api_key'][:20]}...[/cyan]"
    )


# ═══════════════════════════════════════════════════════════════
# CORE COMMANDS (updated with auth headers)
# ═══════════════════════════════════════════════════════════════


@app.command()
def run(
    suite_path: str = typer.Argument(
        ...,
        help="Path to YAML test suite",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model",
    ),
    evaluator: str | None = typer.Option(
        None,
        "--evaluator",
        "-e",
        help="Override evaluator",
    ),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        "-c",
        help="Override how many tests run in parallel",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for CI",
    ),
    fail_under: float = typer.Option(
        0.75,
        "--fail-under",
        help="Exit non-zero if pass rate falls below this (0-1)",
    ),
    compare_to_baseline: bool = typer.Option(
        False,
        "--compare-to-baseline",
        "-B",
        help="After the run, check it against the suite's baseline_run_id "
        "and exit non-zero on a detected regression",
    ),
    baseline_run: str | None = typer.Option(
        None,
        "--baseline-run",
        help="Explicit baseline run id (overrides the suite's baseline_run_id)",
    ),
    report: str | None = typer.Option(
        None,
        "--report",
        help="Write a machine-readable JSON report to this path (for CI)",
    ),
    answers: str | None = typer.Option(
        None,
        "--answers",
        help=(
            "Score answers you already have instead of calling a model: a "
            "JSON, JSON Lines or CSV file of {test_name|prompt, response}. "
            "Only checks that ask an LLM to grade still need a model; name "
            "it with --judge-provider / --judge-model."
        ),
    ),
    judge_provider: str | None = typer.Option(
        None, "--judge-provider", help="Who grades supplied answers (e.g. groq)"
    ),
    judge_model: str | None = typer.Option(
        None, "--judge-model", help="Which model grades supplied answers"
    ),
    strict_cost: bool = typer.Option(
        False,
        "--strict-cost",
        help="Fail if the model has no pricing entry (cost would be $0)",
    ),
):
    """Run a test suite and display results."""
    with open(suite_path) as f:
        suite = yaml.safe_load(f)

    if strict_cost:
        from evalbench.pricing import is_priced

        _p = suite.get("provider", "ollama")
        _m = model or suite.get("model", "")
        if not is_priced(_m, _p):
            console.print(
                f"[bold red]✗ --strict-cost:[/bold red] no pricing entry for "
                f"'{_m}' (provider '{_p}'). Add it to evalbench/pricing.py."
            )
            raise typer.Exit(code=1)

    if model:
        suite["model"] = model

    if evaluator:
        suite["evaluator"] = evaluator

    if concurrency:
        suite["concurrency"] = concurrency

    run_body: dict | None = None
    if answers:
        from evalbench.answers import match_answers, parse_answers
        from evalbench.db.schemas import TestSuite

        try:
            rows = parse_answers(
                Path(answers).read_text(encoding="utf-8"), filename=answers
            )
            _, missing = match_answers(TestSuite(**suite), rows)
        except (OSError, ValueError) as e:
            console.print(f"[red]--answers: {e}[/red]")
            raise typer.Exit(code=1) from e
        if missing:
            console.print(
                f"[yellow]{len(missing)} test(s) have no answer in the file "
                f"and will be reported as unanswered: "
                f"{', '.join(missing[:5])}{' …' if len(missing) > 5 else ''}[/yellow]"
            )
        run_body = {
            "answers": rows,
            "model": model or Path(answers).stem,
            "judge_provider": judge_provider,
            "judge_model": judge_model,
        }
        console.print(
            f"[dim]Scoring {len(rows)} supplied answers — no model is called "
            "for generation.[/dim]"
        )

    headers = _get_headers(api_key)

    with console.status(
        "[bold green]Importing suite..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/import",
            json=suite,
            headers=headers,
            timeout=10.0,
        )

        if r.status_code == 401:
            console.print(
                "[red]Authentication required. "
                "Run `evalbench login` or use --api-key[/red]"
            )
            raise typer.Exit(code=1)

        r.raise_for_status()
        suite_id = r.json()["id"]

    run_id = _run_and_wait(suite_id, headers, suite["model"], body=run_body)

    console.print(
        f"\n[bold green]✓[/bold green] Run completed: "
        f"[cyan]{run_id}[/cyan]"
    )

    r = httpx.get(
        f"{API_URL}/runs/{run_id}/summary",
        headers=headers,
        timeout=10.0,
    )
    summary = r.json()

    table = Table(title=f"Results: {suite['name']}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Model", summary["model"])
    table.add_row("Evaluator", summary["evaluator"])
    table.add_row("Tests", str(summary["total_tests"]))
    table.add_row("Passed", str(summary["passed"]))
    table.add_row("Failed", str(summary["failed"]))

    errors = summary.get("errors", 0)
    if errors:
        table.add_row("Errors", f"[yellow]{errors}[/yellow]")

    rl = summary.get("rate_limited_samples", 0)
    if rl:
        table.add_row("Rate-limited samples", f"[yellow]{rl}[/yellow]")

    # None means nothing was scored — a different statement from 0%, and
    # the one to make when no answer arrived.
    unmeasured = "[dim]— not measured[/dim]"
    pr, avg, lat = (
        summary["pass_rate"], summary["avg_score"], summary["avg_latency_ms"]
    )

    table.add_row(
        "Pass Rate",
        unmeasured if pr is None else f"{pr * 100:.1f}%",
    )

    table.add_row(
        "Avg Score",
        unmeasured if avg is None else f"{avg:.3f}",
    )

    table.add_row(
        "Avg Latency",
        unmeasured if lat is None else f"{lat:.0f} ms",
    )

    table.add_row(
        "Total Tokens",
        str(summary["total_tokens"]),
    )

    tin = summary.get("total_prompt_tokens")
    tout = summary.get("total_completion_tokens")
    if tin or tout:
        table.add_row("Tokens (in / out)", f"{tin} / {tout}")

    cost = summary.get("total_cost_usd", 0) or 0
    table.add_row(
        "Est. Cost (USD)",
        f"${cost:.4f}" if cost else "$0.0000 (local / free)",
    )

    console.print(table)
    console.print(f"[dim]{explain_run(summary)}[/dim]\n")

    by_category = summary.get("by_category") or {}
    if len(by_category) > 1:
        cat_table = Table(title="By Category")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Tests", style="magenta")
        cat_table.add_column("Pass Rate", style="magenta")
        cat_table.add_column("Avg Score", style="magenta")
        cat_table.add_column("Errors", style="yellow")

        for name, stats in sorted(by_category.items()):
            pr = stats.get("pass_rate")
            sc = stats.get("avg_score")
            errs = stats.get("errors", 0)
            cat_table.add_row(
                name,
                str(stats.get("total", 0)),
                # None means nothing in the category could be scored —
                # that is not 0%, it is "no reading".
                f"{pr * 100:.1f}%" if pr is not None else "[dim]— no reading[/dim]",
                f"{sc:.3f}" if sc is not None else "[dim]—[/dim]",
                f"[yellow]{errs}[/yellow]" if errs else "0",
            )

        console.print(cat_table)

    assertion_types = summary.get("assertion_types") or {}
    if assertion_types:
        a_table = Table(title="Assertion Checks")
        a_table.add_column("Type", style="cyan")
        a_table.add_column("Passed", style="green")
        a_table.add_column("Failed", style="red")
        # The type names are jargon; say what each one actually checked.
        a_table.add_column("What it checks", style="dim")

        for a_type, counts in sorted(assertion_types.items()):
            failed = counts.get("failed", 0)
            a_table.add_row(
                a_type,
                str(counts.get("passed", 0)),
                str(failed),
                explain_assertion(a_type, passed=not failed),
            )

        console.print(a_table)

    if errors:
        console.print(
            f"[yellow]⚠️ {errors} test(s) errored and were excluded "
            f"from the pass rate.[/yellow]"
        )

    comp = None
    if compare_to_baseline or baseline_run:
        baseline_id = baseline_run or suite.get("baseline_run_id")
        if not baseline_id:
            console.print(
                "[yellow]No baseline set. Add `baseline_run_id` to the "
                "suite YAML or pass --baseline-run.[/yellow]"
            )
        else:
            comp = _check_regression(baseline_id, run_id, headers)

    # A run that measured nothing cannot clear a quality bar. Treating
    # None as 0 would fail it for the right reason by accident; treating
    # it as a pass would certify an outage as quality.
    gate_pass_rate = (
        summary["pass_rate"] is not None and summary["pass_rate"] >= fail_under
    )
    regression_detected = bool(comp and comp.get("regression_detected"))

    if report:
        Path(report).write_text(
            json.dumps(
                {
                    "suite": suite.get("name"),
                    "run_id": run_id,
                    "summary": summary,
                    "regression": comp,
                    "gate": {
                        "fail_under": fail_under,
                        "pass_rate_ok": gate_pass_rate,
                        "regression_detected": regression_detected,
                        "passed": gate_pass_rate and not regression_detected,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        console.print(f"[dim]Report written to {report}[/dim]")

    if regression_detected:
        raise typer.Exit(code=1)

    if not gate_pass_rate:
        if summary["pass_rate"] is None:
            console.print(
                "[bold red]✗ Nothing was scored — every test failed to get "
                "an answer, so quality could not be measured.[/bold red]"
            )
            raise typer.Exit(1)
        console.print(
            f"[bold red]✗ Pass rate {summary['pass_rate'] * 100:.1f}% "
            f"is below the {fail_under * 100:.0f}% gate.[/bold red]"
        )
        raise typer.Exit(code=1)


@app.command(name="pr-comment")
def pr_comment(
    report: str = typer.Option(
        ..., "--report", help="report.json from `evalbench run --report`"
    ),
    repo: str | None = typer.Option(
        None, "--repo", help="owner/name (default $GITHUB_REPOSITORY)"
    ),
    pr: int | None = typer.Option(
        None, "--pr", help="PR number (default: from the Actions event)"
    ),
    token: str | None = typer.Option(
        None, "--token", help="GitHub token (default $GITHUB_TOKEN)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the comment instead of posting it"
    ),
):
    """Post (or update) an EvalBench result comment on a pull request."""

    from evalbench.ci import render_markdown, resolve_target, upsert_comment

    # utf-8-sig tolerates a BOM (e.g. from PowerShell's Set-Content).
    with open(report, encoding="utf-8-sig") as f:
        data = json.load(f)

    body = render_markdown(data)

    if dry_run:
        console.print(body)
        return

    tok = token or os.getenv("GITHUB_TOKEN")
    if not tok:
        console.print("[red]No GitHub token (--token or $GITHUB_TOKEN).[/red]")
        raise typer.Exit(code=1)

    try:
        target_repo, target_pr = resolve_target(repo, pr)
        action, url = upsert_comment(target_repo, target_pr, tok, body)
    except (ValueError, httpx.HTTPError) as e:
        console.print(f"[red]Could not post comment: {e}[/red]")
        raise typer.Exit(code=1) from e

    console.print(f"[bold green]✓[/bold green] Comment {action}: {url}")


@app.command()
def baseline(
    suite_id: str = typer.Argument(..., help="Suite ID"),
    run_id: str = typer.Argument(..., help="Run ID to promote as baseline"),
    api_key: str | None = typer.Option(None, "--api-key"),
):
    """Promote a completed run as a suite's regression baseline."""
    headers = _get_headers(api_key)
    r = httpx.post(
        f"{API_URL}/suites/{suite_id}/baseline",
        json={"run_id": run_id},
        headers=headers,
        timeout=10.0,
    )
    if r.status_code == 401:
        console.print("[red]Authentication required.[/red]")
        raise typer.Exit(code=1)
    if r.status_code >= 400:
        console.print(f"[bold red]✗[/bold red] {r.json().get('detail', r.text)}")
        raise typer.Exit(code=1)

    data = r.json()
    console.print(
        f"[bold green]✓[/bold green] Baseline for suite "
        f"[cyan]{data['suite_id']}[/cyan] set to run "
        f"[cyan]{data['baseline_run_id']}[/cyan]"
    )


@app.command()
def compare(
    baseline_id: str = typer.Argument(
        ...,
        help="Baseline run ID",
    ),
    current_id: str = typer.Argument(
        ...,
        help="Current run ID",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for CI",
    ),
):
    """Compare two runs for regression."""
    headers = _get_headers(api_key)

    payload = {
        "baseline_run_id": baseline_id,
        "current_run_id": current_id,
    }

    with console.status(
        "[bold green]Analyzing regression..."
    ):
        r = httpx.post(
            f"{API_URL}/regression",
            json=payload,
            headers=headers,
            timeout=15.0,
        )

        if r.status_code == 401:
            console.print(
                "[red]Authentication required.[/red]"
            )
            raise typer.Exit(code=1)

        r.raise_for_status()
        comp = r.json()

    table = Table(title="Regression Analysis")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row(
        "Baseline Mean",
        str(comp.get("baseline_mean")),
    )

    table.add_row(
        "Current Mean",
        str(comp.get("current_mean")),
    )

    table.add_row(
        "Mean Diff",
        str(comp.get("mean_diff")),
    )

    table.add_row(
        "T-Statistic",
        str(comp.get("t_statistic")),
    )

    table.add_row(
        "P-Value",
        str(comp.get("p_value")),
    )

    table.add_row(
        "Significant",
        str(comp.get("significant")),
    )

    console.print(table)
    console.print(f"[dim]{explain_comparison(comp)}[/dim]")

    if comp.get("regression_detected"):
        console.print(
            "\n[bold red]⚠️ REGRESSION DETECTED[/bold red]"
        )
    else:
        console.print(
            "\n[bold green]✅ No Regression Detected[/bold green]"
        )


@app.command()
def models():
    """List available Ollama models."""
    r = httpx.get(
        f"{API_URL}/suites/models",
        timeout=10.0,
    )
    r.raise_for_status()

    data = r.json()

    table = Table(title="Available Models")
    table.add_column("Model", style="cyan")

    for m in data.get("models", []):
        table.add_row(m)

    console.print(table)


@app.command()
def init(
    path: str = typer.Option(
        "suite.yaml",
        "--output",
        "-o",
        help="Output file path",
    ),
):
    """Create a sample test suite."""
    sample = {
        "name": "My Test Suite",
        "model": "llama3.1",
        "evaluator": "semantic",
        "temperature": 0.0,
        "samples": 3,
        "tests": [
            {
                "name": "Example Question",
                "category": "arithmetic",
                "difficulty": "easy",
                "evaluator": "contains",
                "prompt": "What is 2+2?",
                "expected": "4",
                "threshold": 0.99,
            },
            {
                "name": "Example Definition",
                "category": "definitions",
                "difficulty": "medium",
                "evaluator": "semantic",
                "prompt": "In one sentence, what is an operating system?",
                "expected": (
                    "An operating system is software that manages a "
                    "computer's hardware and provides services for "
                    "running application programs."
                ),
                "threshold": 0.55,
            },
        ],
    }

    with open(path, "w") as f:
        yaml.dump(sample, f, sort_keys=False)

    console.print(
        f"[bold green]✓[/bold green] Created sample suite: "
        f"[cyan]{path}[/cyan]"
    )


@app.command()
def security(
    model: str = typer.Option(
        "llama3.1",
        "--model",
        "-m",
        help="Model to test",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for CI",
    ),
):
    """Run the built-in security and adversarial test suite."""

    headers = _get_headers(api_key)

    with console.status(
        "[bold green]Creating security suite..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/security-suite?model={model}",
            headers=headers,
            timeout=10.0,
        )

        if r.status_code == 401:
            console.print(
                "[red]Authentication required.[/red]"
            )
            raise typer.Exit(code=1)

        r.raise_for_status()
        suite_result = r.json()

    suite_id = suite_result["id"]

    console.print(
        f"\n[bold green]✓[/bold green] Security suite created: "
        f"[cyan]{suite_id}[/cyan]"
    )

    console.print(
        f"Tests: {suite_result['test_count']} | "
        f"Categories: {', '.join(suite_result['categories'])}"
    )

    run_id = _run_and_wait(suite_id, headers, model)

    console.print(
        f"\n[bold green]✓[/bold green] Run completed: "
        f"[cyan]{run_id}[/cyan]"
    )

    r = httpx.get(
        f"{API_URL}/runs/{run_id}/summary",
        headers=headers,
        timeout=10.0,
    )
    summary = r.json()

    table = Table(title=f"Security Results: {model}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row(
        "Tests",
        str(summary["total_tests"]),
    )

    table.add_row(
        "Passed (Refused)",
        str(summary["passed"]),
    )

    table.add_row(
        "Failed (Complied)",
        str(summary["failed"]),
    )

    table.add_row(
        "Pass Rate",
        "[dim]— not measured[/dim]"
        if summary["pass_rate"] is None
        else f"{summary['pass_rate'] * 100:.1f}%",
    )

    console.print(table)

    if summary["pass_rate"] is None:
        console.print(
            "\n[bold red]No adversarial prompt got an answer — "
            "this says nothing about the model's safety.[/bold red]"
        )
    elif summary["pass_rate"] < 1.0:
        console.print(
            "\n[bold yellow]⚠️ Some tests were not refused. "
            "Review recommended.[/bold yellow]"
        )
    else:
        console.print(
            "\n[bold green]✅ All adversarial prompts were "
            "correctly refused.[/bold green]"
        )


# ═══════════════════════════════════════════════════════════════
# DAY 14: RESULT EXPORT
# ═══════════════════════════════════════════════════════════════


@app.command()
def export(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to export",
    ),
    format: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="Export format: json or csv",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
    ),
):
    """Export a run to JSON or CSV."""

    if format not in ("json", "csv"):
        console.print(
            "[red]Format must be 'json' or 'csv'[/red]"
        )
        raise typer.Exit(code=1)

    headers = _get_headers(api_key)

    with console.status(
        f"[bold green]Exporting run {run_id} as {format}..."
    ):
        r = httpx.get(
            f"{API_URL}/runs/{run_id}/export?format={format}",
            headers=headers,
            timeout=10.0,
        )

        if r.status_code == 401:
            console.print(
                "[red]Authentication required.[/red]"
            )
            raise typer.Exit(code=1)

        r.raise_for_status()

    data = r.json()

    if format == "json":
        content = json.dumps(
            data["data"],
            indent=2,
        )
    else:
        content = data["content"]

    if output:
        with open(output, "w") as f:
            f.write(content)

        console.print(
            f"[bold green]✓[/bold green] Exported to "
            f"[cyan]{output}[/cyan]"
        )
    else:
        console.print(content)

    console.print(
        f"[dim]Format: {data['format']} | "
        f"Filename: {data['filename']}[/dim]"
    )


@app.command("reset-password")
def reset_password(
    username: str = typer.Option(..., "--username", "-u"),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt="New password",
        hide_input=True,
        confirmation_prompt=True,
    ),
):
    """Reset a user's password by talking to the database directly.

    Recovery for the case that has no other way out: an admin who does
    not know the admin password is locked out of /admin entirely, since
    the web app only accepts a username and password. There was no way
    back short of dropping the users collection.

    Deliberately not an API endpoint. This writes straight to MongoDB, so
    it can only be run by someone with database access — which is the
    right proof of authority for resetting an account, and means no
    unauthenticated reset route exists to attack.
    """
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    from evalbench.api.auth import get_password_hash

    async def _reset() -> tuple[str | None, list[str]]:
        client = AsyncIOMotorClient(settings.mongodb_url)
        try:
            db = client[settings.mongodb_db]
            user = await db.users.find_one({"username": username})
            if not user:
                # Name every account that *does* live here. A machine can
                # easily have a second MongoDB — a locally installed
                # service alongside the one Docker publishes on the same
                # port — and then "no such user" really means "right
                # command, wrong database". Showing the occupants makes
                # that obvious instead of baffling.
                others = [
                    u["username"]
                    async for u in db.users.find({}, {"username": 1})
                ]
                return None, others
            await db.users.update_one(
                {"username": username},
                {"$set": {
                    "hashed_password": get_password_hash(password),
                    # A locked-out account is often also a disabled one.
                    "active": True,
                }},
            )
            return user.get("role", "user"), []
        finally:
            client.close()

    # Say which database is being written to before writing to it.
    console.print(
        f"[dim]Database: {settings.mongodb_url} / "
        f"{settings.mongodb_db}[/dim]"
    )

    try:
        role, others = asyncio.run(_reset())
    except Exception as e:  # noqa: BLE001
        console.print(
            f"[bold red]✗[/bold red] Couldn't reach the database at "
            f"[cyan]{settings.mongodb_url}[/cyan]: {e}\n"
            "[dim]Is the stack up? Try: docker compose up -d mongo[/dim]"
        )
        raise typer.Exit(1) from e

    if role is None:
        console.print(
            f"[bold red]✗[/bold red] No user named [cyan]{username}[/cyan] "
            f"in this database."
        )
        if others:
            console.print(
                f"[dim]It holds: {', '.join(sorted(others))}[/dim]"
            )
        else:
            console.print("[dim]It has no users at all.[/dim]")
        console.print(
            "[dim]If you expected a different set, you are pointed at the "
            "wrong MongoDB — a locally installed server can occupy the "
            "same port Docker publishes. To target the stack's database:\n"
            "  docker compose exec api evalbench reset-password -u "
            f"{username}[/dim]"
        )
        raise typer.Exit(1)

    console.print(
        f"[bold green]✓[/bold green] Password reset for "
        f"[cyan]{username}[/cyan] (role: {role}). "
        "You can sign in to the web app now."
    )


@app.command("merge-suites")
def merge_suites(
    apply: bool = typer.Option(
        False, "--apply", help="Write the merge. Without it, only show the plan."
    ),
    claim: str | None = typer.Option(
        None,
        "--claim",
        help="Assign suites that have no owner (from before accounts "
        "existed) to this username, then merge them with that user's.",
    ),
):
    """Fold duplicate suites — same owner, same name — into one each.

    Until importing became create-or-update, `evalbench run` inserted a
    new suite every time it ran, so a database fills with copies of the
    same benchmark and run history scatters across them. This keeps one
    copy per name (the one holding a baseline, else the newest), points
    every run at it, and deletes the rest. Runs are never deleted.

    Dry run by default: it prints what it would do and stops.
    """
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    from evalbench import maintenance

    async def _plan_and_maybe_apply():
        client = AsyncIOMotorClient(settings.mongodb_url)
        try:
            db = client[settings.mongodb_db]
            suites = [
                s
                async for s in db.suites.find(
                    {}, {"name": 1, "created_by": 1, "baseline_run_id": 1,
                         "created_at": 1},
                )
            ]
            groups = maintenance.plan_merge(suites, claim=claim)
            rows = []
            for g in groups:
                runs = await db.test_runs.count_documents(
                    {"suite_id": {"$in": [str(i) for i in g.drop]}}
                )
                rows.append((g, runs))
            result = (
                await maintenance.apply_merge(db, groups) if apply else None
            )
            return len(suites), rows, result
        finally:
            client.close()

    console.print(
        f"[dim]Database: {settings.mongodb_url} / "
        f"{settings.mongodb_db}[/dim]"
    )
    try:
        total, rows, result = asyncio.run(_plan_and_maybe_apply())
    except Exception as e:  # noqa: BLE001
        console.print(
            f"[bold red]✗[/bold red] Couldn't reach the database at "
            f"[cyan]{settings.mongodb_url}[/cyan]: {e}\n"
            "[dim]Inside the stack: docker compose exec api evalbench "
            "merge-suites[/dim]"
        )
        raise typer.Exit(1) from e

    if not rows:
        console.print(
            f"[bold green]✓[/bold green] {total} suites, no duplicates. "
            "Nothing to do."
        )
        return

    table = Table(title=None, box=None, show_header=True, header_style="dim")
    table.add_column("owner")
    table.add_column("benchmark")
    table.add_column("copies", justify="right")
    table.add_column("runs re-pointed", justify="right")
    for g, runs in rows:
        table.add_row(
            g.owner or "[dim](none)[/dim]", g.name,
            str(len(g.drop) + 1), str(runs),
        )
    console.print(table)
    drop = sum(len(g.drop) for g, _ in rows)
    moved = sum(r for _, r in rows)
    claimed = sum(1 for g, _ in rows if claim and g.owner == claim)

    if result is None:
        console.print(
            f"\n[bold]Dry run.[/bold] Would keep {total - drop} of {total} "
            f"suites, delete {drop} duplicate{'s' if drop != 1 else ''}, "
            f"re-point {moved} run{'s' if moved != 1 else ''}"
            + (f", claim {claimed} for [cyan]{claim}[/cyan]" if claim else "")
            + ".\n[dim]Add --apply to do it.[/dim]"
        )
        return

    console.print(
        f"\n[bold green]✓[/bold green] Kept {total - result['deleted_suites']} "
        f"suites, deleted {result['deleted_suites']}, re-pointed "
        f"{result['moved_runs']} runs, claimed {result['claimed']}."
    )


if __name__ == "__main__":
    app()
