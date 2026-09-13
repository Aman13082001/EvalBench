import example from "@/lib/fixtures/example.json";
import ComparisonReport, { Comparison } from "@/components/ComparisonReport";
import Results from "@/components/Results";
import { RunSummary } from "@/lib/api";
import { Rule } from "@/components/ui";
import SignIn from "@/components/SignIn";

export const metadata = {
  title: "Example evaluation — EvalBench",
  description:
    "A real recorded model comparison: 8 tests, two models, and why a visible score drop still isn't a regression.",
};

/* eslint-disable @typescript-eslint/no-explicit-any */
const data = example as any;

export default function ExamplePage() {
  return (
    <div className="space-y-10">
      <header className="space-y-3">
        <p className="label-xs">§ Example evaluation</p>
        <h1 className="max-w-3xl font-display text-4xl leading-[1.15]">
          Swapping in a cheaper model — did quality actually drop?
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          A real recorded run of{" "}
          <span className="font-mono text-xs">{data.suite_name}</span> — 8 tests
          across factual recall, reasoning, structured output, grounded
          retrieval and open-ended quality — executed against two models and
          compared. No API key needed to read this; nothing here is illustrative.
        </p>
      </header>

      <Rule label="The comparison" />
      <ComparisonReport
        baseline={data.baseline}
        candidate={data.candidate}
        comparison={data.comparison as Comparison}
      />

      <Rule label="The baseline run in full" />
      <p className="max-w-2xl text-sm leading-relaxed text-muted">
        Every test from the baseline model, with each assertion that ran against
        it and the model&rsquo;s raw response. This is the same view every run
        gets in the Workbench.
      </p>
      <Results r={{ ...data.baseline, run_id: "example" } as RunSummary} />

      <Rule />
      <section className="flex flex-col items-start gap-4 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-display text-2xl">Run your own.</p>
          <p className="mt-1 text-sm text-muted">
            Pick a benchmark and a model in the Workbench — with your own
            key or without one.
          </p>
        </div>
        <SignIn className="btn btn-primary shrink-0">Sign in to run one</SignIn>
      </section>
    </div>
  );
}
