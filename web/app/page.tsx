import Link from "next/link";
import HeroDemo from "@/components/HeroDemo";
import { Disclosure, Panel, Rule } from "@/components/ui";

/* Every figure below came out of a real run — see the caption on §2. */
const CAPABILITIES: {
  fig: string;
  title: string;
  plain: string;
  technical: string;
}[] = [
  {
    fig: "2.1",
    title: "Correctness",
    plain: "12 of 12 answers passed every check they were given.",
    technical:
      "pass_rate 1.00 · 4 assertion types (icontains, json-schema, regex, latency) · 12 tests · concurrency 4",
  },
  {
    fig: "2.2",
    title: "Retrieval quality (RAG)",
    plain:
      "Caught two claims the source material never made — a hallucination a human reviewer would skim past.",
    technical:
      "faithfulness 1/3 claims grounded · unsupported: “the exact order depends on timing”, “hard to reproduce” · context-recall and context-precision scored separately",
  },
  {
    fig: "2.3",
    title: "Regression detection",
    plain:
      "Told us model quality genuinely dropped after a change — not that it looked worse, that the drop was real.",
    technical:
      "paired t-test p=0.033 · Cohen's d −0.94 (large) · McNemar 4 regressed / 0 fixed · mean_diff −0.25",
  },
  {
    fig: "2.4",
    title: "Statistical confidence",
    plain:
      "Warned us the suite was too small to trust a 5-point move in either direction.",
    technical:
      "min_samples_for_5pt_mde = 225 at the observed variance · pass rate reported with a 95% percentile bootstrap CI (2000 resamples)",
  },
  {
    fig: "2.5",
    title: "Cost and speed",
    plain: "A full 12-test suite cost three hundredths of a cent.",
    technical:
      "$0.000339 · 962 in / 480 out tokens · $0.10/$0.50 per 1M · 474 ms average · priced per model with a source and as_of date",
  },
  {
    fig: "2.6",
    title: "Safety, both directions",
    plain:
      "Refused both harmful prompts — and answered both harmless ones, instead of refusing everything to look safe.",
    technical:
      "security evaluator · 2/2 refusals on adversarial prompts, 2/2 helpful answers on benign prompts · over-refusal is scored as a failure, not a win",
  },
];

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
          <a
            href="https://github.com/Aman13082001/EvalBench"
            className="btn btn-secondary"
          >
            Read the source
          </a>
        </div>
      </section>

      <Rule label="Fig. 1 · A recorded evaluation" />
      <HeroDemo />

      <Rule label="§2 · What it measures" />
      <section className="space-y-4">
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          Six things, each with a plain answer and the statistics behind it.
          Every figure here came out of a real run against{" "}
          <span className="font-mono text-xs">openai/gpt-oss-20b</span> — none
          of it is illustrative.
        </p>

        <div className="grid gap-4 md:grid-cols-2">
          {CAPABILITIES.map((c) => (
            <Panel key={c.fig} title={c.title} fig={c.fig}>
              <Disclosure plain={c.plain} technical={c.technical} />
            </Panel>
          ))}
        </div>
      </section>

      <Rule label="§3 · Why it is built this way" />
      <section className="grid gap-4 md:grid-cols-3">
        <Panel title="One answer, many checks" fig="3.1">
          <p className="text-sm leading-relaxed text-muted">
            A response is rarely just right or wrong. EvalBench scores the same
            answer on correctness, meaning, rubric quality, groundedness, speed
            and cost — and fails the test if any single check fails.
          </p>
        </Panel>
        <Panel title="Statistics, not vibes" fig="3.2">
          <p className="text-sm leading-relaxed text-muted">
            A lower score is not a regression. EvalBench runs a paired test
            against a promoted baseline and reports an effect size, so you can
            tell a real drop from sampling noise.
          </p>
        </Panel>
        <Panel title="Provider-agnostic" fig="3.3">
          <p className="text-sm leading-relaxed text-muted">
            The same suite runs against a local Ollama model or a hosted one.
            Token counts and cost come back normalised, so comparing models is
            a config change, not a rewrite.
          </p>
        </Panel>
      </section>

      <Rule />
      <section className="flex flex-col items-start gap-4 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-display text-2xl">Run one yourself.</p>
          <p className="mt-1 text-sm text-muted">
            Bring a free API key. No account, nothing stored, results in about
            three seconds.
          </p>
        </div>
        <Link href="/run" className="btn btn-primary shrink-0">
          Open the playground
        </Link>
      </section>
    </div>
  );
}
