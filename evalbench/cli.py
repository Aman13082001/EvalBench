import json
import os
from pathlib import Path

import typer
import httpx
import yaml
from rich.console import Console
from rich.table import Table
from typing import Optional


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


def _get_headers(api_key: Optional[str] = None):
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
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model",
    ),
    evaluator: Optional[str] = typer.Option(
        None,
        "--evaluator",
        "-e",
        help="Override evaluator",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key for CI",
    ),
):
    """Run a test suite and display results."""
    with open(suite_path) as f:
        suite = yaml.safe_load(f)

    if model:
        suite["model"] = model

    if evaluator:
        suite["evaluator"] = evaluator

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

    with console.status(
        f"[bold green]Running tests against {suite['model']}..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/{suite_id}/run",
            headers=headers,
            timeout=120.0,
        )
        r.raise_for_status()
        result = r.json()

    run_id = result["run_id"]

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

    console.print(table)

    if summary["pass_rate"] < 0.75:
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
    api_key: Optional[str] = typer.Option(
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
        "tests": [
            {
                "name": "Example Question",
                "prompt": "What is 2+2?",
                "expected": "4",
                "threshold": 0.8,
            }
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
    api_key: Optional[str] = typer.Option(
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

    with console.status(
        f"[bold green]Running security tests against {model}..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/{suite_id}/run",
            headers=headers,
            timeout=300.0,
        )
        r.raise_for_status()
        result = r.json()

    run_id = result["run_id"]

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
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path",
    ),
    api_key: Optional[str] = typer.Option(
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