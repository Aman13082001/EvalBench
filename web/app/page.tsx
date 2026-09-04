import Link from "next/link";
import { Disclosure, Metric, Panel, Rule } from "@/components/ui";

export default function Home() {
  return (
    <div className="space-y-12">
      <section className="space-y-5">
        <p className="label-xs">§1 · What this is</p>
        <h1 className="max-w-3xl font-display text-4xl leading-[1.15] sm:text-5xl">
          An instrument for measuring what a language model actually does.
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          Write a suite of prompts and the checks each answer must pass. Run it
          against any model. Get back a scored report with statistical
          confidence, cost, and a verdict on whether your last change made
          things worse.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/run" className="btn btn-primary">
            Try it — no account
          </Link>
          <Link href="/styleguide" className="btn btn-secondary">
            Design system
          </Link>
        </div>
      </section>

      {/* F2 replaces this block with the animated pipeline demo. */}
      <Rule label="Fig. 1 · A recorded evaluation" />
      <Panel
        fig="Fig. 1"
        title="Reserved for the pipeline demo"
        caption="Phase F2: prompt → model → response → assertion checks → score → statistics → result, played from a real recorded run."
      >
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
          <Metric
            label="Quality"
            value="91.4"
            unit="%"
            caption="Answers that passed every check."
          />
          <Metric
            label="Faithfulness"
            value="87.2"
            unit="%"
            caption="Claims backed by the source material."
          />
          <Metric
            label="Latency"
            value="0.81"
            unit="s"
            caption="Average time to answer."
          />
          <Metric
            label="Cost"
            value="$0.0002"
            caption="At the model's list price."
          />
        </div>
      </Panel>

      <Rule label="§2 · What it measures" />
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Correctness" fig="2.1">
          <Disclosure
            plain="91% of responses passed every check."
            technical="95% bootstrap CI 87.1–94.2% · n=48 · 2000 resamples"
          />
        </Panel>
        <Panel title="Retrieval quality (RAG)" fig="2.2">
          <Disclosure
            plain="Caught 4 claims the source material didn't support."
            technical="faithfulness 0.67 · context-recall 0.83 · context-precision 0.67"
          />
        </Panel>
        <Panel title="Regression" fig="2.3">
          <Disclosure
            plain="Model quality decreased against the baseline."
            technical="paired t p=0.033 · Cohen's d −0.94 · McNemar 4↓/0↑"
          />
        </Panel>
        <Panel title="Cost and speed" fig="2.4">
          <Disclosure
            plain="This run would cost $0.0003 at list price."
            technical="336 in / 248 out tokens · $0.10/$0.50 per 1M · p95 latency 0.9s"
          />
        </Panel>
      </div>
    </div>
  );
}
