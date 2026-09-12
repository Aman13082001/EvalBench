import { AssertionOutcome, RunSummary } from "./api";

/** Plain-English sentence for one assertion outcome. */
export function explainAssertion(a: AssertionOutcome): string {
  const ok = a.passed;
  switch (a.type) {
    case "exact":
    case "equals":
      return ok ? "Matched the expected answer exactly." : "Didn't match the expected answer exactly.";
    case "contains":
    case "icontains":
      return ok ? "Contains the expected answer." : "Doesn't contain the expected answer.";
    case "regex":
      return ok ? "Matches the expected format." : "Doesn't match the expected format.";
    case "json-schema":
      return ok ? "Replied with correctly structured JSON." : "Reply wasn't valid, correctly-structured JSON.";
    case "semantic":
      return ok
        ? "Means the same thing as the expected answer, even if worded differently."
        : "Doesn't mean the same thing as the expected answer.";
    case "judge":
      return ok ? "An AI judge rated this a good answer." : "An AI judge rated this a weak answer.";
    case "llm-rubric":
      return ok ? "Meets the grading criteria." : "Doesn't meet the grading criteria.";
    case "latency":
      return ok ? "Responded within the time budget." : "Took longer than the time budget allowed.";
    case "cost":
      return ok ? "Stayed within the cost budget." : "Cost more than the budget allowed.";
    case "faithfulness":
      return ok
        ? "Stuck to facts backed by the source material — no made-up claims."
        : "Included claims not backed by the source material (a hallucination).";
    case "context-recall":
      return ok
        ? "The source material had what was needed to answer."
        : "The source material was missing information needed to answer.";
    case "context-precision":
      return ok
        ? "The retrieved material was relevant to the question."
        : "Some of the retrieved material was irrelevant noise.";
    default:
      return ok ? "Passed this check." : "Failed this check.";
  }
}

/** One-sentence, non-technical summary of a whole run. */
export function explainRun(r: RunSummary): string {
  const n = r.scored_tests;
  const p = r.passed;
  if (n === 0) return "No tests could be scored.";
  if (p === n) return `All ${n} answers passed every check you asked for.`;
  if (p === 0) return `None of the ${n} answers passed — worth a closer look.`;
  return `${p} out of ${n} answers passed everything you checked for; ${n - p} missed at least one check.`;
}

/** Whether a difference between two runs of the same suite is real.
 *  Mirrors `explain_comparison` in evalbench/explain.py. */
export function explainComparison(c: {
  mean_diff: number | null;
  p_value: number | null;
  test_count?: number;
  regression_detected?: boolean | null;
  min_samples_for_5pt_mde?: number | null;
}): string {
  if (c.mean_diff == null) return "Not enough overlapping tests to compare these two runs.";
  const pts = Math.abs(c.mean_diff) * 100;
  const dir = c.mean_diff > 0 ? "better" : "worse";
  const n = c.test_count ?? 0;
  const p = c.p_value;
  if (c.regression_detected && p != null)
    return `Quality really did drop: ${pts.toFixed(1)} points ${dir}, and with ${n} tests behind it that is unlikely to be chance (p = ${p.toFixed(3)}). Worth investigating before shipping.`;
  if (p == null) return `The newer run scored ${pts.toFixed(1)} points ${dir}.`;
  if (p < 0.05)
    return `The newer run is ${pts.toFixed(1)} points ${dir}, and that looks like a real difference rather than luck (p = ${p.toFixed(3)}).`;
  const need = c.min_samples_for_5pt_mde;
  const hint = need && n && need > n ? ` To reliably detect a change this small you would need around ${need} tests, not ${n}.` : "";
  return `The newer run scored ${pts.toFixed(1)} points ${dir}, but that is within normal run-to-run variation — not a real change (p = ${p.toFixed(3)}; anything above 0.05 means it could easily be luck).${hint}`;
}

/** Two models on the same suite. Symmetric — neither is "the baseline".
 *  Mirrors `explain_model_comparison` in evalbench/explain.py. The line
 *  that matters is the "within expected noise" one: a raw pass-rate
 *  comparison never says it. */
export function explainModelComparison(
  modelA: string,
  modelB: string,
  c: {
    mean_diff: number | null;
    p_value: number | null;
    test_count?: number;
    min_samples_for_5pt_mde?: number | null;
  }
): string {
  if (c.mean_diff == null) return "Not enough tests in common to compare these two models.";
  const pts = Math.abs(c.mean_diff) * 100;
  const n = c.test_count ?? 0;
  if (pts < 0.05) return `${modelA} and ${modelB} scored the same on these ${n} tests.`;
  const [ahead, behind] = c.mean_diff > 0 ? [modelB, modelA] : [modelA, modelB];
  const p = c.p_value;
  if (p == null) return `${ahead} scored ${pts.toFixed(1)} points higher than ${behind}.`;
  if (p < 0.05)
    return `${ahead} scored ${pts.toFixed(1)} points higher than ${behind}, and the difference is real — not luck (p = ${p.toFixed(3)}, ${n} paired tests).`;
  const need = c.min_samples_for_5pt_mde;
  const hint = need && n && need > n ? ` Telling them apart reliably would take around ${need} tests, not ${n}.` : "";
  return `${ahead} scored ${pts.toFixed(1)} points higher than ${behind}, but that is within expected noise — it does not show one model is better (p = ${p.toFixed(3)}, ${n} paired tests).${hint}`;
}
