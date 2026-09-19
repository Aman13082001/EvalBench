import { Disclosure, Metric, Panel, Rule, Status } from "@/components/ui";
import { endpointHost, type Comparison, type RunSummary } from "@/lib/api";
import { explainComparison, explainModelComparison } from "@/lib/explain";

/* Re-exported so pages can import the type alongside the component. */
export type { Comparison };

type Summary = RunSummary;

/* Null means nothing was scored — a different statement from 0%,
   which would claim every answer was wrong. */
const pct = (x: number | null) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;

/** Two CI ranges on a shared 0–100% scale. Overlap is the whole point:
 *  it shows visually why a big-looking gap may not be significant. */
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
            style={{ left: `${(s.pass_rate ?? 0) * 100}%` }}
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

/* ────────────────────────────────────────────────────────────────
   Every sentence below is derived from the numbers. An earlier version
   carried prose written for one specific recorded comparison ("the
   smaller model", "the drop", "moderate, not large") — true for that
   fixture, false the moment the component was reused. A report that
   narrates a conclusion the data doesn't support is worse than no
   report, so nothing here is allowed to assume a direction, a size, or
   a verdict.

   mode="regression": baseline vs. a newer run — "did it get worse?"
   mode="models":     two models on one benchmark — "which is better?"
   ──────────────────────────────────────────────────────────────── */

export type ComparisonMode = "regression" | "models";

function effectLabel(d: number | null): string {
  if (d == null) return "Effect size not available.";
  const m = Math.abs(d);
  const size =
    m < 0.2 ? "negligible" : m < 0.5 ? "small" : m < 0.8 ? "moderate" : "large";
  return `The effect size is ${size}.`;
}

function ciOverlap(a: Summary, b: Summary): boolean | null {
  if (!a.pass_rate_ci || !b.pass_rate_ci) return null;
  return (
    a.pass_rate_ci[0] <= b.pass_rate_ci[1] &&
    b.pass_rate_ci[0] <= a.pass_rate_ci[1]
  );
}

export default function ComparisonReport({
  baseline,
  candidate,
  comparison,
  mode = "regression",
}: {
  baseline: Summary;
  candidate: Summary;
  comparison: Comparison;
  mode?: ComparisonMode;
}) {
  const c = comparison;
  const moved = c.per_test.filter((t) => (t.delta ?? 0) !== 0);
  const cats = Array.from(
    new Set([
      ...Object.keys(baseline.by_category),
      ...Object.keys(candidate.by_category),
    ])
  );
  const models = mode === "models";
  const labelA = models ? "Model A" : "Baseline";
  const labelB = models ? "Model B" : "Candidate";

  // What to call each side. A custom endpoint is part of the name — the
  // same model name means different things on different servers. And
  // two runs of the same model are told apart by their panel letters,
  // not by a sentence that says "X scored higher than X".
  const nameOf = (r: RunSummary) => {
    const host = endpointHost(r.base_url);
    return host ? `${r.model} at ${host}` : r.model;
  };
  let nameA = nameOf(baseline);
  let nameB = nameOf(candidate);
  if (nameA === nameB) {
    nameA = labelA;
    nameB = labelB;
  }

  const verdict = models
    ? explainModelComparison(nameA, nameB, c)
    : explainComparison(c);
  const significant = c.p_value != null && c.p_value < 0.05;
  // A run that scored nothing is not "lower" — it is not comparable,
  // and colouring it as a loss would read as a quality verdict.
  const comparable =
    candidate.pass_rate != null && baseline.pass_rate != null;
  const higher = !comparable
    ? null
    : candidate.pass_rate! > baseline.pass_rate!
      ? "b"
      : candidate.pass_rate! < baseline.pass_rate!
        ? "a"
        : null;
  const overlap = ciOverlap(baseline, candidate);

  // categories where the two runs actually differ, for the caption
  const catMoves = cats
    .map((k) => ({
      k,
      d:
        (candidate.by_category[k]?.pass_rate ?? 0) -
        (baseline.by_category[k]?.pass_rate ?? 0),
    }))
    .filter((x) => Math.abs(x.d) > 1e-9);
  const catCaption =
    catMoves.length === 0
      ? "Every category scored the same on both runs."
      : `Categories that moved: ${catMoves
          .map((x) => `${x.k} ${x.d > 0 ? "+" : ""}${(x.d * 100).toFixed(0)} pts`)
          .join(", ")}. A single blended pass rate would hide this.`;

  const pLine =
    c.p_value == null
      ? "no p-value available"
      : significant
        ? `p = ${c.p_value.toFixed(3)} — below 0.05, unlikely to be chance`
        : `p = ${c.p_value.toFixed(3)} — above 0.05, could easily be chance`;

  return (
    <div className="space-y-6">
      {/* ── The verdict ── */}
      <Panel fig="Verdict">
        <p className="font-display text-xl leading-snug">{verdict}</p>
        <p className="mt-2 font-mono text-[11px] text-muted tnum">
          {pLine}
          {c.effect_size != null && ` · Cohen's d ${c.effect_size.toFixed(2)}`}
          {` · ${c.test_count} paired tests`}
        </p>
      </Panel>

      {/* ── Side by side ── */}
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title={labelA} fig="A" caption={nameOf(baseline)}>
          <div className="grid grid-cols-2 gap-4">
            <Metric
              label="Pass rate"
              value={pct(baseline.pass_rate)}
              sub={`${baseline.passed}/${baseline.scored_tests}`}
              tone={higher === "a" ? "success" : higher === "b" ? "error" : "text"}
            />
            <Metric
              label="Avg score"
              value={baseline.avg_score?.toFixed(3) ?? "—"}
            />
            <Metric
              label="Cost"
              value={
                baseline.total_cost_usd
                  ? `$${baseline.total_cost_usd.toFixed(6)}`
                  : "unpriced"
              }
            />
            <Metric
              label="Latency"
              value={
                baseline.avg_latency_ms == null
                  ? "—"
                  : String(Math.round(baseline.avg_latency_ms))
              }
              unit={baseline.avg_latency_ms == null ? undefined : "ms"}
            />
          </div>
        </Panel>
        <Panel title={labelB} fig="B" caption={nameOf(candidate)}>
          <div className="grid grid-cols-2 gap-4">
            <Metric
              label="Pass rate"
              value={pct(candidate.pass_rate)}
              sub={`${candidate.passed}/${candidate.scored_tests}`}
              tone={higher === "b" ? "success" : higher === "a" ? "error" : "text"}
            />
            <Metric
              label="Avg score"
              value={candidate.avg_score?.toFixed(3) ?? "—"}
            />
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
              value={
                candidate.avg_latency_ms == null
                  ? "—"
                  : String(Math.round(candidate.avg_latency_ms))
              }
              unit={candidate.avg_latency_ms == null ? undefined : "ms"}
            />
          </div>
        </Panel>
      </div>

      {/* ── Is the difference real? ── */}
      <Panel
        title="Is the difference real?"
        fig="Fig. 2"
        caption={
          overlap == null
            ? "The bars are 95% bootstrap confidence intervals on the pass rate."
            : overlap
              ? "The bars are 95% bootstrap confidence intervals on the pass rate. They overlap, so the true difference could plausibly be zero."
              : "The bars are 95% bootstrap confidence intervals on the pass rate. They do not overlap — the two runs are separable even allowing for sampling noise."
        }
      >
        <CiBars a={baseline} b={candidate} />
        <div className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
          <Disclosure
            plain={
              c.p_value == null
                ? "No significance test could be run."
                : significant
                  ? "The difference is statistically significant."
                  : "The difference is not statistically significant."
            }
            technical={`paired t-test p=${c.p_value} · threshold 0.05 · n=${c.test_count}`}
          />
          <Disclosure
            plain={effectLabel(c.effect_size)}
            technical={`Cohen's d = ${c.effect_size} (|d| 0.2 small, 0.5 medium, 0.8 large)`}
          />
          {c.mcnemar && (
            <Disclosure
              plain={`${c.mcnemar.regressions} test(s) went pass→fail, ${c.mcnemar.fixes} went fail→pass.`}
              technical={`exact McNemar on paired outcomes · ${c.mcnemar.discordant} discordant pairs · p=${c.mcnemar.p_value}`}
            />
          )}
          {c.min_samples_for_5pt_mde && (
            <Disclosure
              plain={`To resolve a move this size reliably you'd need about ${c.min_samples_for_5pt_mde} tests.`}
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
        {moved.length === 0 ? (
          <p className="text-sm text-muted">
            Every test scored identically on both runs.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="label-xs pb-2 font-normal">Test</th>
                <th className="label-xs pb-2 text-right font-normal">{labelA}</th>
                <th className="label-xs pb-2 text-right font-normal">{labelB}</th>
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
        )}
        {moved.length > 0 && (
          <p className="mt-3 font-mono text-xs text-muted">
            {c.per_test.length - moved.length} test(s) scored identically.
          </p>
        )}
      </Panel>

      {/* ── Per category ── */}
      <Panel title="By category" fig="Fig. 4" caption={catCaption}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="label-xs pb-2 font-normal">Category</th>
              <th className="label-xs pb-2 text-right font-normal">{labelA}</th>
              <th className="label-xs pb-2 text-right font-normal">{labelB}</th>
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

      {/* ── The gate — only meaningful for a regression check ── */}
      {!models && (
        <>
          <Rule />
          <div className="flex flex-wrap items-center gap-3">
            {c.regression_detected ? (
              <Status state="fail">gate would block this change</Status>
            ) : (
              <Status state="pass">gate would allow this change</Status>
            )}
            <span className="text-sm text-muted">
              <span className="font-mono text-xs">
                evalbench run --compare-to-baseline
              </span>{" "}
              {c.regression_detected
                ? "exits non-zero here — a real, significant drop."
                : significant
                  ? "exits 0 here — significant, but not a drop past the regression threshold."
                  : "exits 0 here — any difference is within noise."}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
