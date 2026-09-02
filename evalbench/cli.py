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


def _run_and_wait(suite_id: str, headers: dict, model: str) -> str:
    """Kick off an async run and poll until it finishes. Returns the run id."""

    r = httpx.post(
        f"{API_URL}/suites/{suite_id}/run",
        headers=headers,
        timeout=30.0,
    )
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
                timeout=10.0,
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
):
    """Run a test suite and display results."""
    with open(suite_path) as f:
        suite = yaml.safe_load(f)

    if model:
        suite["model"] = model

    if evaluator:
        suite["evaluator"] = evaluator

    if concurrency:
        suite["concurrency"] = concurrency

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

    run_id = _run_and_wait(suite_id, headers, suite["model"])

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

    table.add_row(
        "Pass Rate",
        f"{summary['pass_rate'] * 100:.1f}%",
    )

    table.add_row(
        "Avg Score",
        f"{summary['avg_score']:.3f}",
    )

    table.add_row(
        "Avg Latency",
        f"{summary['avg_latency_ms']:.0f} ms",
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

    by_category = summary.get("by_category") or {}
    if len(by_category) > 1:
        cat_table = Table(title="By Category")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Tests", style="magenta")
        cat_table.add_column("Pass Rate", style="magenta")
        cat_table.add_column("Avg Score", style="magenta")
        cat_table.add_column("Errors", style="yellow")

        for name, stats in sorted(by_category.items()):
            cat_table.add_row(
                name,
                str(stats.get("total", 0)),
                f"{stats.get('pass_rate', 0) * 100:.1f}%",
                f"{stats.get('avg_score', 0):.3f}",
                str(stats.get("errors", 0)),
            )

        console.print(cat_table)

    assertion_types = summary.get("assertion_types") or {}
    if assertion_types:
        a_table = Table(title="Assertion Checks")
        a_table.add_column("Type", style="cyan")
        a_table.add_column("Passed", style="green")
        a_table.add_column("Failed", style="red")

        for a_type, counts in sorted(assertion_types.items()):
            a_table.add_row(
                a_type,
                str(counts.get("passed", 0)),
                str(counts.get("failed", 0)),
            )

        console.print(a_table)

    if errors:
        console.print(
            f"[yellow]⚠️ {errors} test(s) errored and were excluded "
            f"from the pass rate.[/yellow]"
        )

    if summary["pass_rate"] < fail_under:
        console.print(
            f"[bold red]✗ Pass rate {summary['pass_rate'] * 100:.1f}% "
            f"is below the {fail_under * 100:.0f}% gate.[/bold red]"
        )
        raise typer.Exit(code=1)


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
        f"{summary['pass_rate'] * 100:.1f}%",
    )

    console.print(table)

    if summary["pass_rate"] < 1.0:
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


if __name__ == "__main__":
    app()
