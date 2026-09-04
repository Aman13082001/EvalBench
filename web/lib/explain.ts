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
