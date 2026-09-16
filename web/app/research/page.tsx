import Link from "next/link";
import study from "@/lib/fixtures/power-study.json";
import PowerCurve from "@/components/PowerCurve";
import { Disclosure, Metric, Panel, Rule } from "@/components/ui";

export const metadata = {
  title: "How many tests does an eval suite need? — EvalBench",
  description:
    "An empirical power analysis of LLM regression detection. Power is 21% at ten tests and does not cross 80% until between forty and sixty.",
};

/* eslint-disable @typescript-eslint/no-explicit-any */
const s = study as any;
const pct = (x: number) => `${Math.round(x * 100)}%`;

export default function ResearchPage() {
  return (
    <article className="space-y-10">
      <header className="space-y-3">
        <p className="label-xs">§ Research · {s.generated}</p>
        <h1 className="max-w-3xl font-display text-4xl leading-[1.15]">
          How many tests does an LLM eval suite need?
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          An empirical power analysis of regression detection, measured with
          EvalBench on real model outputs. The short answer is that most eval
          suites are far too small to gate a deploy on — and they fail in the
          direction that hurts.
        </p>
        <p className="font-mono text-xs text-muted">
          {s.n_tests} tests · baseline{" "}
          <span className="text-text">{s.baseline_model}</span> · candidate{" "}
          <span className="text-text">{s.candidate_model}</span> ·{" "}
          {s.resamples.toLocaleString()} bootstrap resamples per size
        </p>
      </header>

      <Rule label="The question" />
      <section className="max-w-2xl space-y-3 text-base leading-relaxed">
        <p>
          Teams gate deploys on eval suites, and those suites are usually
          small — a dozen prompts, maybe thirty. When such a suite reports
          &ldquo;quality dropped&rdquo;, how often is that verdict trustworthy?
          And how many tests does it actually take before a real regression is
          reliably caught?
        </p>
      </section>

      <Rule label="Method" />
      <section className="grid gap-4 md:grid-cols-3">
        <Panel title="Collect" fig="1">
          <p className="text-sm leading-relaxed text-muted">
            A {s.n_tests}-test suite spanning factual recall, arithmetic,
            multi-step reasoning, structured output and definitions, run once
            against two models of clearly different capability. Deterministic
            assertions only — no LLM judge — so the variance measured comes
            from the model, not the grader.
          </p>
        </Panel>
        <Panel title="Observe" fig="2">
          <p className="text-sm leading-relaxed text-muted">
            The real effect was a mean per-test score difference of{" "}
            <span className="font-mono text-xs">{s.mean_diff}</span> (
            {s.baseline_mean} → {s.candidate_mean}), with a standard deviation
            of differences of{" "}
            <span className="font-mono text-xs">{s.diff_sd}</span>.
          </p>
        </Panel>
        <Panel title="Resample" fig="3">
          <p className="text-sm leading-relaxed text-muted">
            For each suite size <em>n</em>, {s.resamples.toLocaleString()}{" "}
            bootstrap draws of <em>n</em> test-pairs were taken with
            replacement and EvalBench&rsquo;s own detector run on each. The
            share of draws reporting a regression is the empirical power.
          </p>
        </Panel>
      </section>

      <Rule label="Result" />
      <Panel
        fig="Fig. 1"
        title="Probability the regression is detected"
        caption={`Each point is ${s.resamples.toLocaleString()} bootstrap draws at that suite size. The dashed line is 80% power, the conventional threshold for calling a test adequately powered.`}
      >
        <PowerCurve curve={s.curve} nAt80={s.n_for_80_power} />
      </Panel>

      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <Metric
          label="Power at n=10"
          value={pct(s.power_at_10)}
          caption="A ten-prompt suite misses this real regression four times in five."
          tone="error"
        />
        <Metric
          label="80% power at"
          value={`n≈${s.n_for_80_power}`}
          caption="Tests needed before the verdict is dependable."
          tone="success"
        />
        <Metric
          label="Effect size"
          value={String(s.effect_size)}
          caption="Cohen's d — a moderate effect, not a subtle one."
        />
        <Metric
          label="Observed p"
          value={String(s.observed_p_value)}
          caption={`At the full n=${s.n_tests}, the drop is significant.`}
        />
      </div>

      <Rule label="Findings" />
      <section className="space-y-4">
        <Panel title="Small suites miss real regressions" fig="4.1">
          <Disclosure
            plain={`At ten tests the detector fires only ${pct(
              s.power_at_10
            )} of the time on an effect this size. A team running that suite would miss the same genuine degradation four times in five, and reasonably conclude nothing had changed.`}
            technical={`power(n=10) = ${s.power_at_10} · power(n=30) = ${
              s.curve.find((c: any) => c.n === 30)?.power
            } · power(n=60) = ${
              s.curve.find((c: any) => c.n === 60)?.power
            }`}
          />
        </Panel>

        <Panel title="The failure is silent, and in the wrong direction" fig="4.2">
          <p className="text-sm leading-relaxed">
            A small suite rarely invents a regression that isn&rsquo;t there;
            it fails to see one that is. For a deploy gate that means the
            failure mode is <em>ship it</em>, not <em>investigate</em> — the
            expensive direction to be wrong in.
          </p>
        </Panel>

        <Panel title="The tool's own estimate is a safe upper bound" fig="4.3">
          <Disclosure
            plain={`EvalBench reported that ${s.min_samples_for_5pt_mde} tests would be needed. The measured requirement was about ${s.n_for_80_power}. The estimate is conservative rather than wrong — it targets a 5-point shift, and the effect here was much larger.`}
            technical={`min_samples_for_5pt_mde = ${s.min_samples_for_5pt_mde} (normal approximation, 80% power, α=0.05, sd=${s.diff_sd}) vs empirical n₈₀ = ${s.n_for_80_power} for an observed shift of ${s.mean_diff}`}
          />
        </Panel>

        <Panel title="Effect size matters as much as sample size" fig="4.4">
          <Disclosure
            plain={`Cohen's d here was ${s.effect_size} — moderate. A suite big enough to catch a model swap can still be blind to a subtle prompt change, because power depends on both.`}
            technical={`d = ${s.effect_size} · |d| 0.2 small, 0.5 medium, 0.8 large · power scales with d√n`}
          />
        </Panel>
      </section>

      <Rule label="Implication" />
      <section className="max-w-2xl space-y-3 text-base leading-relaxed">
        <p>
          The practical guidance is uncomfortable:{" "}
          <strong>the eval suite most teams have is too small to gate on.</strong>{" "}
          A suite that cannot detect the regressions it exists to catch offers
          assurance without evidence.
        </p>
        <p className="text-muted">
          Two mitigations follow directly, and EvalBench implements both:
          report a <strong>confidence interval</strong> on the pass rate rather
          than a bare number, so overlap is visible at a glance; and report the{" "}
          <strong>required sample size</strong> next to the verdict, so
          &ldquo;no regression detected&rdquo; reads as &ldquo;not detectable
          at this n&rdquo; rather than &ldquo;no regression exists&rdquo;.
        </p>
      </section>

      <Rule label="Limitations" />
      <section className="max-w-2xl space-y-2 text-sm leading-relaxed text-muted">
        <p>
          One effect size, one model pair, one task distribution. The absolute
          numbers do not transfer; the shape of the curve and the direction of
          the bias do.
        </p>
        <p>
          Bootstrap resampling from {s.n_tests} real tests approximates a larger
          suite drawn from the same distribution. A genuinely larger suite would
          add task diversity this method cannot simulate.
        </p>
        <p>
          Assertions were deterministic by design. Suites relying on an LLM
          judge carry additional grader variance, which would shift the curve
          right.
        </p>
      </section>

      {/* Not a section. Reproducibility matters — a study nobody can
          check is a blog post with numbers — but almost no one browsing
          a page will clone a repo and run a script mid-paragraph, and
          the command needs a provider key. One line keeps the claim
          checkable and lets the page end on the comparison instead. */}
      <p className="text-xs leading-relaxed text-muted">
        Check it yourself:{" "}
        <span className="font-mono text-[11px] text-accent">
          python scripts/run_study_power.py
        </span>{" "}
        re-runs the suite against both models and the resampling (needs a
        Groq key). Every paired score and the full curve are in{" "}
        <span className="font-mono text-[11px]">research/power-study.json</span>
        ; the write-up is{" "}
        <span className="font-mono text-[11px]">research/REPORT.md</span>.
      </p>

      <Rule />
      <section className="flex flex-col items-start gap-4 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-display text-2xl">See it on a real comparison.</p>
          <p className="mt-1 text-sm text-muted">
            The example report shows this exact tension on eight tests.
          </p>
        </div>
        <Link href="/example" className="btn btn-primary shrink-0">
          View example evaluation
        </Link>
      </section>
    </article>
  );
}
