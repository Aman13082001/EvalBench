import typer
import httpx
import yaml
from rich.console import Console
from rich.table import Table
from typing import Optional

app = typer.Typer(help="EvalBench — Local LLM Evaluation CLI")
console = Console()
API_URL = "http://localhost:8000"


@app.command()
def run(
    suite_path: str = typer.Argument(..., help="Path to YAML test suite"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override model"),
    evaluator: Optional[str] = typer.Option(None, "--evaluator", "-e", help="Override evaluator"),
):
    """Run a test suite and display results."""
    with open(suite_path) as f:
        suite = yaml.safe_load(f)

    if model:
        suite["model"] = model

    if evaluator:
        suite["evaluator"] = evaluator

    # Import suite
    with console.status("[bold green]Importing suite..."):
        r = httpx.post(
            f"{API_URL}/suites/import",
            json=suite,
            timeout=10.0
        )
        r.raise_for_status()
        suite_id = r.json()["id"]

    # Run suite
    with console.status(
        f"[bold green]Running tests against {suite['model']}..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/{suite_id}/run",
            timeout=120.0
        )
        r.raise_for_status()
        result = r.json()

    run_id = result["run_id"]

    console.print(
        f"\n[bold green]✓[/bold green] Run completed: "
        f"[cyan]{run_id}[/cyan]"
    )

    # Fetch summary
    r = httpx.get(
        f"{API_URL}/runs/{run_id}/summary",
        timeout=10.0
    )
    summary = r.json()

    # Display table
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
        f"{summary['pass_rate'] * 100:.1f}%"
    )
    table.add_row(
        "Avg Score",
        f"{summary['avg_score']:.3f}"
    )
    table.add_row(
        "Avg Latency",
        f"{summary['avg_latency_ms']:.0f} ms"
    )
    table.add_row(
        "Total Tokens",
        str(summary["total_tokens"])
    )

    console.print(table)

    # Add exit code for CI
    if summary["pass_rate"] < 0.75:
        raise typer.Exit(code=1)


@app.command()
def compare(
    baseline_id: str = typer.Argument(..., help="Baseline run ID"),
    current_id: str = typer.Argument(..., help="Current run ID"),
):
    """Compare two runs for regression."""
    payload = {
        "baseline_run_id": baseline_id,
        "current_run_id": current_id
    }

    with console.status("[bold green]Analyzing regression..."):
        r = httpx.post(
            f"{API_URL}/regression",
            json=payload,
            timeout=15.0
        )
        r.raise_for_status()
        comp = r.json()

    table = Table(title="Regression Analysis")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row(
        "Baseline Mean",
        str(comp.get("baseline_mean"))
    )
    table.add_row(
        "Current Mean",
        str(comp.get("current_mean"))
    )
    table.add_row(
        "Mean Diff",
        str(comp.get("mean_diff"))
    )
    table.add_row(
        "T-Statistic",
        str(comp.get("t_statistic"))
    )
    table.add_row(
        "P-Value",
        str(comp.get("p_value"))
    )
    table.add_row(
        "Significant",
        str(comp.get("significant"))
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
        timeout=10.0
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
        help="Output file path"
    )
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
        help="Model to test"
    ),
):
    """Run the built-in security and adversarial test suite."""

    with console.status(
        "[bold green]Creating security suite..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/security-suite?model={model}",
            timeout=10.0
        )
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

    # Run it
    with console.status(
        f"[bold green]Running security tests against {model}..."
    ):
        r = httpx.post(
            f"{API_URL}/suites/{suite_id}/run",
            timeout=300.0
        )
        r.raise_for_status()
        result = r.json()

    run_id = result["run_id"]

    console.print(
        f"\n[bold green]✓[/bold green] Run completed: "
        f"[cyan]{run_id}[/cyan]"
    )

    # Fetch summary
    r = httpx.get(
        f"{API_URL}/runs/{run_id}/summary",
        timeout=10.0
    )
    summary = r.json()

    table = Table(title=f"Security Results: {model}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row(
        "Tests",
        str(summary["total_tests"])
    )
    table.add_row(
        "Passed (Refused)",
        str(summary["passed"])
    )
    table.add_row(
        "Failed (Complied)",
        str(summary["failed"])
    )
    table.add_row(
        "Pass Rate",
        f"{summary['pass_rate'] * 100:.1f}%"
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


if __name__ == "__main__":
    app()