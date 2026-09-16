import { RunSummary } from "@/lib/api";
import { explainAssertion, explainRun } from "@/lib/explain";
import { Disclosure, Metric, Panel, Rule, Status } from "@/components/ui";

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export default function Results({ r }: { r: RunSummary }) {
  const cats = Object.entries(r.by_category);
  const atypes = Object.entries(r.assertion_types);

  return (
    <div className="space-y-6">
      <Panel fig="Result">
        <p className="font-display text-lg leading-snug">{explainRun(r)}</p>
        {r.pass_rate_ci && (
          <p className="mt-1 font-mono text-xs text-muted tnum">
            95% CI {pct(r.pass_rate_ci[0])}–{pct(r.pass_rate_ci[1])} · n=
            {r.scored_tests}
          </p>
        )}
      </Panel>

      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <Metric
          label="Pass rate"
          value={pct(r.pass_rate)}
          sub={`${r.passed}/${r.scored_tests}`}
          caption="Answers that passed every check."
          tone={r.pass_rate >= 0.8 ? "success" : "error"}
        />
        <Metric
          label="Avg score"
          value={r.avg_score.toFixed(3)}
          caption="0 = failed, 1 = perfect."
        />
        <Metric
          label="Est. cost"
          value={
            r.total_cost_usd
              ? `$${r.total_cost_usd.toFixed(5)}`
              : r.total_prompt_tokens + r.total_completion_tokens > 0
                ? "unpriced"
                : "$0"
          }
          sub={`${r.total_prompt_tokens}/${r.total_completion_tokens} tok`}
          caption={
            r.total_cost_usd || r.total_prompt_tokens + r.total_completion_tokens === 0
              ? "At the model's list price."
              : "No list price on file for this model."
          }
          tone="accent"
        />
        <Metric
          label="Avg latency"
          value={String(Math.round(r.avg_latency_ms))}
          unit="ms"
          caption={r.errors > 0 ? "Average over the tests that answered." : "Average time to answer."}
        />
      </div>

      {/* Two different things go wrong, and conflating them produced
          "0 of 51 tests never got an answer" on a run where nothing
          failed. A test that got no answer is missing from the numbers.
          A test that lost *samples* is in the numbers but measured less
          precisely — the quieter problem, and the one worth naming. */}
      {(r.errors > 0 || r.rate_limited_samples > 0) && (
        <div className="border border-warning/60 p-3 text-sm">
          {r.errors > 0 && (
            <p>
              <span className="font-medium text-warning">
                {r.errors} of {r.total_tests} tests never got an answer.
              </span>{" "}
              They are left out of every number above — the pass rate is over
              the {r.scored_tests} that did.
            </p>
          )}
          {r.rate_limited_samples > 0 && (
            <p className={r.errors > 0 ? "mt-2" : undefined}>
              <span className="font-medium text-warning">
                {r.rate_limited_samples} sample
                {r.rate_limited_samples === 1 ? " was" : "s were"} dropped to
                rate limits.
              </span>{" "}
              {r.undersampled_tests
                ? `${r.undersampled_tests} test${
                    r.undersampled_tests === 1 ? " was" : "s were"
                  } scored on fewer than the ${
                    r.samples_requested ?? "requested"
                  } samples asked for.`
                : "Every test still got the samples it asked for."}{" "}
              {!!r.undersampled_tests && (
                <span className="text-muted">
                  Sampling several times is what makes a pass a majority
                  vote rather than one draw, so those results carry more
                  noise and the interval above is wider than it would
                  otherwise be.
                </span>
              )}
            </p>
          )}
          {r.rate_limited_samples > 0 && (
            <p className="mt-1 text-xs text-muted">
              Free tiers cap requests per minute. EvalBench pauses and retries
              when it is limited; past that, try fewer samples, a smaller
              benchmark, your own key, or run again in a few minutes.
            </p>
          )}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {cats.length > 1 && (
          <Panel
            title="By category"
            fig="A"
            caption="Where the model is strong or weak, by category. Tests that never got an answer are shown but not scored."
          >
            <table className="w-full text-sm">
              <tbody>
                {cats.map(([name, s]) => {
                  const scored = s.scored ?? s.total - (s.errors ?? 0);
                  return (
                    <tr key={name} className="border-t border-line first:border-0">
                      <td className="py-1.5">{name}</td>
                      <td className="py-1.5 text-right font-mono text-xs text-muted tnum">
                        {scored}/{s.total}
                        {s.errors > 0 && (
                          <span className="ml-1 text-warning">· {s.errors} no answer</span>
                        )}
                      </td>
                      <td className="py-1.5 text-right font-mono text-sm tnum">
                        {s.pass_rate == null ? (
                          <span className="text-muted">— no reading</span>
                        ) : (
                          pct(s.pass_rate)
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        )}

        {atypes.length > 0 && (
          <Panel
            title="Checks run"
            fig="B"
            caption="Every kind of check used across all answers, and how many passed."
          >
            <ul className="space-y-2 text-sm">
              {atypes.map(([t, c]) => (
                <li key={t} className="flex items-baseline justify-between gap-3">
                  <span className="flex-1">
                    {explainAssertion({
                      type: t,
                      passed: true,
                      score: 1,
                      detail: "",
                    })}
                  </span>
                  <span className="shrink-0 font-mono text-xs tnum">
                    <span className="text-success">{c.passed}✓</span>
                    {c.failed > 0 && (
                      <span className="ml-1.5 text-error">{c.failed}✗</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>

      <Rule label="Per test" />
      <div className="space-y-3">
        {r.results.map((t) => {
          /* Same rule as the API's summary: a test is "errored" only when
             no sample produced an answer. One lost sample out of three
             still leaves a scored test — noted, not flagged. */
          const errored = !!t.error && !(t.runs ?? 0);
          const lostSamples = !errored && (t.rate_limited ?? 0) > 0;
          return (
          <Panel
            key={t.test_name}
            title={t.test_name}
            right={
              <span className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-muted tnum">
                  {errored ? "no answer" : `${t.score ?? 0} · ${Math.round(t.latency_ms)}ms`}
                </span>
                <Status state={errored ? "warn" : t.passed ? "pass" : "fail"}>
                  {errored ? "error" : undefined}
                </Status>
              </span>
            }
          >
            {errored && (
              <p className="mb-2 text-sm text-warning">
                Couldn&rsquo;t get an answer from the provider — not scored, not
                counted against the model.
                <span className="ml-2 font-mono text-[11px] text-muted">
                  {String(t.error).slice(0, 140)}
                </span>
              </p>
            )}
            {lostSamples && (
              <p className="mb-2 font-mono text-[11px] text-muted">
                scored on {t.runs} sample{t.runs === 1 ? "" : "s"} · {t.rate_limited} rate-limited
              </p>
            )}
            {t.assertions && t.assertions.length > 0 && (
              <ul className="space-y-2 text-sm">
                {t.assertions.map((a, i) => (
                  <li key={i}>
                    {a.detail ? (
                      <Disclosure
                        plain={
                          <span>
                            <span
                              className={a.passed ? "text-success" : "text-error"}
                            >
                              {a.passed ? "✓ " : "✗ "}
                            </span>
                            {explainAssertion(a)}
                          </span>
                        }
                        technical={`${a.type}: ${a.detail}`}
                      />
                    ) : (
                      <span>
                        <span className={a.passed ? "text-success" : "text-error"}>
                          {a.passed ? "✓ " : "✗ "}
                        </span>
                        {explainAssertion(a)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <details className="mt-3">
              <summary className="label-xs cursor-pointer">
                model&rsquo;s actual response
              </summary>
              <pre className="mt-2 whitespace-pre-wrap break-words border-l-2 border-line pl-3 font-mono text-xs text-muted">
                {t.actual || t.error || "(empty)"}
              </pre>
            </details>
          </Panel>
          );
        })}
      </div>
    </div>
  );
}
