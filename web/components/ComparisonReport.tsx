import { Disclosure, Metric, Panel, Rule, Status } from "@/components/ui";

type Summary = {
  model: string;
  passed: number;
  scored_tests: number;
  pass_rate: number;
  avg_score: number;
  pass_rate_ci: [number, number] | null;
  total_cost_usd: number;
  avg_latency_ms: number;
  by_category: Record<string, { total: number; pass_rate: number }>;
};

type PerTest = {
  test_name: string;
  baseline_score: number | null;
  current_score: number | null;
  delta: number | null;
  regressed: boolean;
};

export type Comparison = {
  mean_diff: number;
  p_value: number | null;
  effect_size: number | null;
  significant: boolean;
  regression_detected: boolean | null;
  min_samples_for_5pt_mde: number | null;
  test_count: number;
  per_test: PerTest[];
  mcnemar: {
    regressions: number;
    fixes: number;
    discordant: number;
    p_value: number;
  } | null;
};

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

/** Two CI ranges on a shared 0–100% scale. Overlap is the whole point:
 *  it shows visually why a big-looking drop isn't significant. */
function CiBars({ a, b }: { a: Summary; b: Summary }) {
  const row = (s: Summary, tone: string) => {
    const ci = s.pass_rate_ci;
    if (!ci) return null;
    const left = ci[0] * 100;
    const width = Math.max((ci[1] - ci[0]) * 100, 1.5);
    return (
      <div className="space-y-1">
        <div className="flex items-baseline justify-between font-mono text-[11px]">
          <span className="text-muted">{s.model}</span>
          <span className="tnum">
            {pct(s.pass_rate)} · CI {pct(ci[0])}–{pct(ci[1])}
          </span>
        </div>
        <div className="relative h-5 border border-line bg-surface-sunk">
          <div
            className={`absolute top-0 h-full ${tone} opacity-30`}
            style={{ left: `${left}%`, width: `${width}%` }}
          />
          <div
            className={`absolute top-0 h-full w-0.5 ${tone}`}
            style={{ left: `${s.pass_rate * 100}%` }}
          />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {row(a, "bg-primary")}
      {row(b, "bg-accent")}
      <div className="flex justify-between font-mono text-[10px] text-muted">
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

export default function ComparisonReport({
  baseline,
  candidate,
  comparison,
}: {
  baseline: Summary;
  candidate: Summary;
  comparison: Comparison;
}) {
  const c = comparison;
  const moved = c.per_test.filter((t) => (t.delta ?? 0) !== 0);
  const cats = Object.keys(baseline.by_category);

  return (
    <div className="space-y-6">
      {/* ── The verdict ── */}
      <Panel fig="Verdict">
        <p className="font-display text-xl leading-snug">
          The smaller model scored {(c.mean_diff * -1).toFixed(3)} lower — and
          EvalBench still refuses to call it a regression.
        </p>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          {baseline.passed}/{baseline.scored_tests} passed on{" "}
          <span className="font-mono text-xs">{baseline.model}</span> against{" "}
          {candidate.passed}/{candidate.scored_tests} on{" "}
          <span className="font-mono text-xs">{candidate.model}</span>. That
          looks decisive. With {c.test_count} tests it isn&rsquo;t: the
          confidence intervals overlap and the paired test comes back{" "}
          <span className="font-mono text-xs tnum">p={c.p_value}</span>. A tool
          that told you &ldquo;regression&rdquo; here would be lying to you.
        </p>
      </Panel>

      {/* ── Side by side ── */}
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Baseline" fig="A" caption={baseline.model}>
          <div className="grid grid-cols-2 gap-4">
            <Metric
              label="Pass rate"
              value={pct(baseline.pass_rate)}
              sub={`${baseline.passed}/${baseline.scored_tests}`}
              tone="success"
            />
            <Metric label="Avg score" value={baseline.avg_score.toFixed(3)} />
            <Metric
              label="Cost"
              value={`$${baseline.total_cost_usd.toFixed(6)}`}
            />
            <Metric
              label="Latency"
              value={String(Math.round(baseline.avg_latency_ms))}
              unit="ms"
            />
          </div>
        </Panel>
        <Panel title="Candidate" fig="B" caption={candidate.model}>
          <div className="grid grid-cols-2 gap-4">
            <Metric
              label="Pass rate"
              value={pct(candidate.pass_rate)}
              sub={`${candidate.passed}/${candidate.scored_tests}`}
              tone="error"
            />
            <Metric label="Avg score" value={candidate.avg_score.toFixed(3)} />
            <Metric
              label="Cost"
              value={
                candidate.total_cost_usd
                  ? `$${candidate.total_cost_usd.toFixed(6)}`
                  : "unpriced"
              }
            />
            <Metric
              label="Latency"
              value={String(Math.round(candidate.avg_latency_ms))}
              unit="ms"
            />
          </div>
        </Panel>
      </div>

      {/* ── Why it's not significant ── */}
      <Panel
        title="Why that isn't a regression"
        fig="Fig. 2"
        caption="The bars are 95% bootstrap confidence intervals on the pass rate. They overlap, so the true difference could plausibly be zero."
      >
        <CiBars a={baseline} b={candidate} />
        <div className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
          <Disclosure
            plain="The drop is not statistically significant."
            technical={`paired t-test p=${c.p_value} · threshold 0.05 · n=${c.test_count}`}
          />
          <Disclosure
            plain="The effect size is moderate, not large."
            technical={`Cohen's d = ${c.effect_size} (|d| 0.5 ≈ medium, 0.8 ≈ large)`}
          />
          {c.mcnemar && (
            <Disclosure
              plain={`${c.mcnemar.regressions} tests flipped pass→fail, ${c.mcnemar.fixes} flipped fail→pass.`}
              technical={`exact McNemar on paired outcomes · ${c.mcnemar.discordant} discordant pairs · p=${c.mcnemar.p_value}`}
            />
          )}
          {c.min_samples_for_5pt_mde && (
            <Disclosure
              plain={`To resolve a move this size you'd need about ${c.min_samples_for_5pt_mde} tests.`}
              technical={`min_samples_for_5pt_mde = ${c.min_samples_for_5pt_mde} at the observed variance · 80% power, α=0.05`}
            />
          )}
        </div>
      </Panel>

      {/* ── What actually moved ── */}
      <Panel
        title="What actually moved"
        fig="Fig. 3"
        caption="Per-test deltas. Aggregate scores hide this — one test can collapse while another improves."
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="label-xs pb-2 font-normal">Test</th>
              <th className="label-xs pb-2 text-right font-normal">Baseline</th>
              <th className="label-xs pb-2 text-right font-normal">Candidate</th>
              <th className="label-xs pb-2 text-right font-normal">Δ</th>
            </tr>
          </thead>
          <tbody>
            {moved.map((t) => (
              <tr key={t.test_name} className="border-b border-line/60">
                <td className="py-1.5 font-mono text-xs">{t.test_name}</td>
                <td className="py-1.5 text-right font-mono text-xs tnum">
                  {t.baseline_score?.toFixed(3)}
                </td>
                <td className="py-1.5 text-right font-mono text-xs tnum">
                  {t.current_score?.toFixed(3)}
                </td>
                <td
                  className={`py-1.5 text-right font-mono text-xs tnum ${
                    (t.delta ?? 0) < 0 ? "text-error" : "text-success"
                  }`}
                >
                  {(t.delta ?? 0) > 0 ? "+" : ""}
                  {t.delta?.toFixed(3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 font-mono text-xs text-muted">
          {c.per_test.length - moved.length} test(s) scored identically.
        </p>
      </Panel>

      {/* ── Per category ── */}
      <Panel
        title="Where it degraded"
        fig="Fig. 4"
        caption="One blended pass rate would have hidden that reasoning and structured output took the hit while factual recall held."
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="label-xs pb-2 font-normal">Category</th>
              <th className="label-xs pb-2 text-right font-normal">Baseline</th>
              <th className="label-xs pb-2 text-right font-normal">Candidate</th>
            </tr>
          </thead>
          <tbody>
            {cats.map((k) => {
              const a = baseline.by_category[k]?.pass_rate ?? 0;
              const b = candidate.by_category[k]?.pass_rate ?? 0;
              return (
                <tr key={k} className="border-b border-line/60">
                  <td className="py-1.5">{k}</td>
                  <td className="py-1.5 text-right font-mono text-xs tnum">
                    {pct(a)}
                  </td>
                  <td
                    className={`py-1.5 text-right font-mono text-xs tnum ${
                      b < a ? "text-error" : b > a ? "text-success" : ""
                    }`}
                  >
                    {pct(b)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <Rule />
      <div className="flex flex-wrap items-center gap-3">
        <Status state="pass">gate would allow this change</Status>
        <span className="text-sm text-muted">
          <span className="font-mono text-xs">
            evalbench run --compare-to-baseline
          </span>{" "}
          exits 0 here — the drop is real-looking but unproven.
        </span>
      </div>
    </div>
  );
}
