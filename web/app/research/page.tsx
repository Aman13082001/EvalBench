import Link from "next/link";
import study from "@/lib/fixtures/power-study.json";
import judgeStudy from "@/lib/fixtures/judge-study.json";
import PowerCurve from "@/components/PowerCurve";
import JudgeSpread from "@/components/JudgeSpread";
import { Disclosure, Metric, Panel, Rule } from "@/components/ui";

export const metadata = {
  title: "The studies — EvalBench",
  description:
    "Two studies of how LLM evaluation is measured: a ten-test suite catches a real regression 21% of the time, and a judge switch is a third of a 5-point gate's budget.",
};

/* eslint-disable @typescript-eslint/no-explicit-any */
const s = study as any;
const j = judgeStudy as any;
const pct = (x: number) => `${Math.round(x * 100)}%`;
const pts = (x: number) => `${(x * 100).toFixed(1)} pts`;
const short = (m: string) => m.split("/").pop();

export default function ResearchPage() {
  return (
    <article className="space-y-10">
      <header className="space-y-3">
        <p className="label-xs">§ Research · two studies</p>
        <h1 className="max-w-3xl font-display text-4xl leading-[1.15]">
          LLM evaluation is itself badly measured.
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          Every benchmark on this site reports what it can actually see. These
          are the two studies, run with EvalBench on real model outputs, that
          say why it has to: how many tests a regression gate needs before its
          verdict means anything, and how much of a judged score is the judge.
        </p>
      </header>

      {/* ── Study 1 ─────────────────────────────────────────── */}
      <Rule label="Study 1" />
      <header className="space-y-3" id="power">
        <h2 className="max-w-3xl font-display text-3xl leading-[1.15]">
          How many tests does an LLM eval suite need?
        </h2>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          An empirical power analysis of regression detection. The short
          answer is that most eval suites are far too small to gate a deploy
          on — and they fail in the direction that hurts.
        </p>
        <p className="font-mono text-xs text-muted">
          {s.generated} · {s.n_tests} tests · baseline{" "}
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
          judge carry additional grader variance — how much is the second
          study.
        </p>
      </section>

      {/* ── Study 2 ─────────────────────────────────────────── */}
      <Rule label="Study 2" />
      <header className="space-y-3" id="judge">
        <h2 className="max-w-3xl font-display text-3xl leading-[1.15]">
          How much of a judged score is the judge?
        </h2>
        <p className="max-w-2xl text-base leading-relaxed text-muted">
          When a check asks a model to grade an answer against a rubric, the
          number has two authors: the model that answered and the model that
          graded. Sixty answers were generated once and frozen; three judge
          models then scored every one of them five times, with the same
          prompt and parser a real run uses. What moved was the judge.
        </p>
        <p className="font-mono text-xs text-muted">
          {j.generated} · {j.n_answers} answers from{" "}
          <span className="text-text">{j.answerers.strong}</span> and{" "}
          <span className="text-text">{j.answerers.weak}</span> · judges{" "}
          {j.judges.map((m: string, i: number) => (
            <span key={m}>
              <span className="text-text">{short(m)}</span>
              {i < j.judges.length - 1 ? ", " : ""}
            </span>
          ))}{" "}
          · {j.repeats} repeats · {j.calls} judge calls
        </p>
      </header>

      <Rule label="Method" />
      <section className="grid gap-4 md:grid-cols-3">
        <Panel title="Freeze" fig="1">
          <p className="text-sm leading-relaxed text-muted">
            A {j.n_tests}-test suite of prompts where a rubric is the only
            honest check — explanations, summaries, soft constraints,
            refusals, code review. Two models answered once; the answers were
            written to files and never regenerated. If the answers could
            change, a moving score could be either author.
          </p>
        </Panel>
        <Panel title="Re-score" fig="2">
          <p className="text-sm leading-relaxed text-muted">
            Each judge scored every frozen answer {j.repeats} times through
            EvalBench&rsquo;s production rubric prompt, call and parser — the
            bytes a user&rsquo;s run sends. Every raw reply was kept, so a
            reply the parser could not read counts as what it is, not as a
            score.
          </p>
        </Panel>
        <Panel title="Decompose" fig="3">
          <p className="text-sm leading-relaxed text-muted">
            Every score is indexed by (answer, judge, repeat). A two-way
            random-effects decomposition splits the variance into the
            answers, a judge&rsquo;s constant offset, judges disagreeing
            differently on different answers, and re-asking. The arithmetic
            was proven on simulated data with planted components first.
          </p>
        </Panel>
      </section>

      <Rule label="Result" />
      <Panel
        fig="Fig. 2"
        title="Every answer, every judge"
        caption="One column per answer, sorted by its average score. A dot is one judge's mean over five repeats; the bar is the range across those repeats. Judges agree on the clearly good and clearly bad answers and split on the ones in between."
      >
        <JudgeSpread spread={j.spread} judges={j.judges} cutoff={j.pass_cutoff} />
      </Panel>

      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <Metric
          label="The answers"
          value={pct(j.components.share.answer)}
          caption="Share of variance that is the answers actually differing — the signal."
          tone="success"
        />
        <Metric
          label="The judge"
          value={pct(j.components.share.answer_x_judge + j.components.share.retest)}
          caption="Judges disagreeing on specific answers, plus re-asking. Not zero."
          tone="warning"
        />
        <Metric
          label="Judge switch"
          value={`±${pts(j.floor.switch_judge_sd)}`}
          caption={`What changing judge model does to a ${j.n_tests}-test mean, before the model changes.`}
        />
        <Metric
          label="No verdict"
          value={`${j.no_verdict.total} of ${j.calls}`}
          caption="Replies with no score in them. They used to be a pass."
          tone="error"
        />
      </div>

      <Rule label="Findings" />
      <section className="space-y-4">
        <Panel title="For telling two models apart, the judge is not the problem" fig="5.1">
          <Disclosure
            plain={`Every judge saw the gap between the strong and the weak model, and saw it at nearly the same size (${Object.values(j.gap).map((g: any) => `+${(g.gap * 100).toFixed(0)}`).join(", ")} points). Asked again, a judge gives the same answer almost every time. On a difference this large the grader is a rounding error.`}
            technical={`test–retest ICC ${Object.values(j.retest).map((r: any) => r.icc.toFixed(2)).join(" / ")} · Spearman between judges ${j.agreement.map((a: any) => a.spearman.toFixed(2)).join(" / ")} · judge offset variance ${j.components.share.judge} · gap ${j.floor.observed_gap_min.toFixed(2)}–${j.floor.observed_gap_max.toFixed(2)}`}
          />
        </Panel>

        <Panel title="For catching a small regression, the judge is a third of the budget" fig="5.2">
          <Disclosure
            plain={`A deploy gate looks for a 5-point drop. On a ${j.n_tests}-test benchmark, a judge switch moves the mean by about ${pts(j.floor.switch_judge_sd)} and a re-run by about ${pts(j.floor.rerun_same_judge_sd)} — together roughly ${Math.round(j.gate.both_vs_mde * 100)}% of the effect the gate is looking for, before the model has changed at all. That is not noise you can ignore; it is noise you have to subtract. Every judged benchmark on this site now shows its share of it.`}
            technical={`switch floor sqrt(σ²_J + σ²_AJ/n) = ${j.floor.switch_judge_sd} · rerun floor σ_E/√n = ${j.floor.rerun_same_judge_sd} · combined ${j.gate.both_sd} vs MDE 0.05 → ${Math.round(j.gate.both_vs_mde * 100)}%`}
          />
        </Panel>

        <Panel title="Judges matter most where answers are best" fig="5.3">
          <Disclosure
            plain={`In the ${j.near_ceiling.category} category the answers averaged ${j.near_ceiling.mean.toFixed(2)} and ${pct(j.near_ceiling.judge_share)} of what variance remained was the judge — the highest of any category. Near the ceiling there is little answer variance left, so what is left is the judge's taste. That is the regime a mature product lives in, and exactly where teams watch for small drops.`}
            technical={Object.entries(j.by_category).map(([c, b]: [string, any]) => `${c}: mean ${b.grand_mean.toFixed(2)}, judge share ${pct(b.share.judge + b.share.answer_x_judge)}`).join(" · ")}
          />
        </Panel>

        <Panel title="A judge can decline to judge — and that used to be a pass" fig="5.4">
          <Disclosure
            plain={`${j.no_verdict.total} of ${j.calls} replies contained no verdict at all, every one from ${Object.keys(j.no_verdict.by_judge).map(short).join(", ")} and every one on a ${Object.keys(j.no_verdict.by_category).join(", ")} prompt: the judge would not engage with a grading prompt that quotes a harmful request. EvalBench's parser read an empty reply as 3 out of 5, which is 0.6 — the default pass cutoff. A lock-picking walkthrough, graded by a judge that refused to look at it, passed. Fixed: no verdict is now a judge error on the result, never a score. It is the second parser bug found by being able to score frozen answers; the first was a 1 out of 5 reading as perfect.`}
            technical={`empty replies ${j.no_verdict.empty} · parse fallback path returned 3/5 → 0.6 ≥ cutoff 0.6 → passed=True · fix: parse_judge_output raises ValueError on no verdict; _check_llm_rubric reports "judge error"`}
          />
        </Panel>
      </section>

      <Rule label="The premise, tested as written" />
      <section className="max-w-2xl space-y-3 text-base leading-relaxed">
        <p>
          The design said in advance what would falsify it: if the judge
          terms came in under {pct(j.premise.noise_share_threshold)} of
          variance <em>and</em> every pair of judges rank-correlated above{" "}
          {j.premise.spearman_threshold}, judges are a fine instrument and the
          premise is wrong for this class of check.
        </p>
        <p className="text-muted">
          Measured: <span className="font-mono text-text">{pct(j.premise.noise_share)}</span> and{" "}
          <span className="font-mono text-text">ρ ≥ {j.premise.min_spearman.toFixed(2)}</span>.{" "}
          {j.premise.falsified
            ? "Both thresholds were met. The premise is falsified on this benchmark, and that is the result."
            : "Neither threshold was met, so the premise stands — narrowly. The honest headline is the one in the numbers: not the problem for telling models apart, a third of the budget for catching a small drop, and most of what moves near the ceiling."}
        </p>
      </section>

      <Rule label="Limitations" />
      <section className="max-w-2xl space-y-2 text-sm leading-relaxed text-muted">
        <p>
          Three judges, one rubric style, one task distribution. The judge
          offset came out at zero here; a judge from a different family or a
          rubric written differently could well carry one.
        </p>
        <p>
          Five repeats at temperature 0.1 bound the retest term well; they
          say nothing about how a judge drifts across a model update, which
          is a switch by another name.
        </p>
        <p>
          The floor shown on each benchmark scales this study&rsquo;s
          per-answer spread to that benchmark&rsquo;s size. It is a
          transferred estimate, not a measurement of that benchmark — the
          benchmark&rsquo;s own resolution, from its run history, is.
        </p>
      </section>

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
