"""Plain-English renderings of the numbers EvalBench reports.

The web app has had this since the observation that `pass_rate_ci` and
`cosine=0.625` wall off anyone who isn't already an evaluation engineer
(``web/lib/explain.ts``). The CLI printed the raw terms and nothing else,
which is worse, because the terminal output is what people screenshot and
show to someone.

Wording is deliberately kept in step with ``web/lib/explain.ts`` so the
same result reads the same way wherever it is shown.
"""

from __future__ import annotations

_ASSERTION_SENTENCES: dict[str, tuple[str, str]] = {
    # type: (passed, failed)
    "exact": (
        "Matched the expected answer exactly.",
        "Didn't match the expected answer exactly.",
    ),
    "equals": (
        "Matched the expected answer exactly.",
        "Didn't match the expected answer exactly.",
    ),
    "contains": (
        "Contains the expected answer.",
        "Doesn't contain the expected answer.",
    ),
    "icontains": (
        "Contains the expected answer.",
        "Doesn't contain the expected answer.",
    ),
    "regex": (
        "Matches the expected format.",
        "Doesn't match the expected format.",
    ),
    "json-schema": (
        "Replied with correctly structured JSON.",
        "Reply wasn't valid, correctly-structured JSON.",
    ),
    "semantic": (
        "Means the same thing as the expected answer, even if worded "
        "differently.",
        "Doesn't mean the same thing as the expected answer.",
    ),
    "judge": (
        "An AI judge rated this a good answer.",
        "An AI judge rated this a weak answer.",
    ),
    "llm-rubric": (
        "Meets the grading criteria.",
        "Doesn't meet the grading criteria.",
    ),
    "latency": (
        "Responded within the time budget.",
        "Took longer than the time budget allowed.",
    ),
    "cost": (
        "Stayed within the cost budget.",
        "Cost more than the budget allowed.",
    ),
    "faithfulness": (
        "Stuck to facts backed by the source material — no made-up claims.",
        "Included claims not backed by the source material "
        "(a hallucination).",
    ),
    "context-recall": (
        "The source material had what was needed to answer.",
        "The source material was missing information needed to answer.",
    ),
    "context-precision": (
        "The retrieved material was relevant to the question.",
        "Some of the retrieved material was irrelevant noise.",
    ),
    "security": (
        "Handled the safety case correctly.",
        "Handled the safety case wrongly — either it should have declined "
        "and didn't, or it refused something harmless.",
    ),
}


def explain_assertion(assertion_type: str, passed: bool) -> str:
    """One sentence for a single check."""
    pair = _ASSERTION_SENTENCES.get(assertion_type)
    if pair is None:
        return "Passed this check." if passed else "Failed this check."
    return pair[0] if passed else pair[1]


def explain_run(summary: dict) -> str:
    """One sentence for a whole run, in the words a non-engineer uses."""
    scored = summary.get("scored_tests") or summary.get("total_tests") or 0
    passed = summary.get("passed", 0)
    errors = summary.get("errors", 0)

    if scored == 0:
        return "No tests could be scored."

    parts = [
        f"{passed} out of {scored} answers passed everything you checked for."
    ]
    if errors:
        if summary.get("provider") == "answers":
            # Nothing was called, so nothing could fail to connect: the
            # file simply had no row for these tests.
            parts.append(
                f"{errors} test(s) had no answer in the file you supplied "
                "and are left out of the score."
            )
        else:
            parts.append(
                f"{errors} test(s) couldn't run at all (a connection or "
                "provider problem, not the model's fault) and are left out "
                "of the score."
            )
    return " ".join(parts)


def explain_comparison(comp: dict) -> str:
    """Say whether a difference between two runs is real.

    This is the number people misread most often. A pass rate that moved
    several points looks like a change; whether it *is* one depends on how
    many tests were behind it. Saying so in words is the whole point of
    running the statistics.
    """
    diff = comp.get("mean_diff")
    p = comp.get("p_value")
    n = comp.get("test_count") or 0

    if diff is None:
        return "Not enough overlapping tests to compare these two runs."

    pts = abs(diff) * 100
    direction = "better" if diff > 0 else "worse"

    # A detected regression is the headline; say it plainly.
    if comp.get("regression_detected"):
        return (
            f"Quality really did drop: {pts:.1f} points {direction}, and with "
            f"{n} tests behind it that is unlikely to be chance "
            f"(p = {p:.3f}, where below 0.05 means 'probably real'). "
            "Worth investigating before shipping."
        )

    if p is None:
        return f"The newer run scored {pts:.1f} points {direction}."

    if p < 0.05:
        return (
            f"The newer run is {pts:.1f} points {direction}, and that looks "
            f"like a real difference rather than luck (p = {p:.3f})."
        )

    hint = ""
    need = comp.get("min_samples_for_5pt_mde")
    if need and n and need > n:
        hint = (
            f" To reliably detect a change this small you would need around "
            f"{need} tests, not {n}."
        )
    return (
        f"The newer run scored {pts:.1f} points {direction}, but that is "
        f"within normal run-to-run variation — not a real change "
        f"(p = {p:.3f}; anything above 0.05 means it could easily be luck)."
        + hint
    )


def explain_model_comparison(model_a: str, model_b: str, comp: dict) -> str:
    """Two models on the same suite. Symmetric — neither is "the baseline".

    The regression wording asks "did it get worse?"; this asks "which is
    better, and can we tell?". The second question is the one a raw
    pass-rate comparison answers wrongly most often, because a higher
    number is read as "better" even when the gap is inside the noise.
    """
    diff = comp.get("mean_diff")
    p = comp.get("p_value")
    n = comp.get("test_count") or 0

    if diff is None:
        return "Not enough tests in common to compare these two models."

    pts = abs(diff) * 100
    if pts < 0.05:
        return (
            f"{model_a} and {model_b} scored the same on these {n} tests."
        )

    ahead, behind = (model_b, model_a) if diff > 0 else (model_a, model_b)

    if p is None:
        return f"{ahead} scored {pts:.1f} points higher than {behind}."

    if p < 0.05:
        return (
            f"{ahead} scored {pts:.1f} points higher than {behind}, and "
            f"the difference is real — not luck (p = {p:.3f}, {n} paired "
            "tests)."
        )

    hint = ""
    need = comp.get("min_samples_for_5pt_mde")
    if need and n and need > n:
        hint = (
            f" Telling them apart reliably would take around {need} tests, "
            f"not {n}."
        )
    return (
        f"{ahead} scored {pts:.1f} points higher than {behind}, but that "
        f"is within expected noise — it does not show one model is better "
        f"(p = {p:.3f}, {n} paired tests)." + hint
    )
