import { RunSummary } from "@/lib/api";
import { explainAssertion, explainRun } from "@/lib/explain";

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

function ci(pair: [number, number] | null): string {
  if (!pair) return "";
  return ` [${pct(pair[0])}–${pct(pair[1])}]`;
}

function Stat({
  label,
  value,
  sub,
  caption,
}: {
  label: string;
  value: string;
  sub?: string;
  caption: string;
}) {
  return (
    <div className="card p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-xl font-bold">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
      <div className="mt-1 text-xs text-slate-500">{caption}</div>
    </div>
  );
}

export default function Results({ r }: { r: RunSummary }) {
  const cats = Object.entries(r.by_category);
  const atypes = Object.entries(r.assertion_types);

  return (
    <div className="space-y-4">
      <div className="card border-accent/40 p-4">
        <p className="text-base">{explainRun(r)}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Pass rate"
          value={pct(r.pass_rate)}
          sub={`${r.passed}/${r.scored_tests}${ci(r.pass_rate_ci)}`}
          caption="Share of answers that passed every check."
        />
        <Stat
          label="Avg score"
          value={r.avg_score.toFixed(3)}
          caption="0 = failed, 1 = perfect. Averaged across all answers."
        />
        <Stat
          label="Est. cost"
          value={r.total_cost_usd ? `$${r.total_cost_usd.toFixed(5)}` : "$0"}
          sub={`${r.total_prompt_tokens}/${r.total_completion_tokens} tok`}
          caption="What this run would cost at the model's list price."
        />
        <Stat
          label="Avg latency"
          value={`${Math.round(r.avg_latency_ms)} ms`}
          caption="Average time the model took to answer."
        />
      </div>

      {(r.errors > 0 || r.rate_limited_samples > 0) && (
        <p className="text-sm text-warn">
          {r.errors > 0 && `${r.errors} test(s) errored (infrastructure issue, not a wrong answer). `}
          {r.rate_limited_samples > 0 &&
            `${r.rate_limited_samples} sample(s) were rate-limited by the provider — try again shortly.`}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {cats.length > 1 && (
          <div className="card p-3">
            <h3 className="mb-1 text-sm font-semibold">By category</h3>
            <p className="mb-2 text-xs text-slate-500">
              Where the model is strong vs. weak, grouped by the `category` tag on each test.
            </p>
            <table className="w-full text-sm">
              <tbody>
                {cats.map(([name, s]) => (
                  <tr key={name} className="border-t border-line/50">
                    <td className="py-1">{name}</td>
                    <td className="py-1 text-right text-slate-400">{s.total}</td>
                    <td className="py-1 text-right">{pct(s.pass_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {atypes.length > 0 && (
          <div className="card p-3">
            <h3 className="mb-1 text-sm font-semibold">Checks run</h3>
            <p className="mb-2 text-xs text-slate-500">
              Every kind of check used across all answers, and how many passed.
            </p>
            <table className="w-full text-sm">
              <tbody>
                {atypes.map(([t, c]) => (
                  <tr key={t} className="border-t border-line/50">
                    <td className="py-1" title={t}>
                      {explainAssertion({ type: t, passed: true, score: 1, detail: "" })}
                    </td>
                    <td className="py-1 text-right text-good">{c.passed}✓</td>
                    <td className="py-1 text-right text-bad">
                      {c.failed ? `${c.failed}✗` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="space-y-2">
        {r.results.map((t) => (
          <div key={t.test_name} className="card p-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold">
                {t.passed ? (
                  <span className="text-good">PASS</span>
                ) : (
                  <span className="text-bad">FAIL</span>
                )}{" "}
                {t.test_name}
              </span>
              <span className="text-xs text-slate-400">
                score {t.score ?? 0} · {Math.round(t.latency_ms)} ms
              </span>
            </div>
            {t.assertions && t.assertions.length > 0 && (
              <ul className="mt-2 space-y-1.5 text-sm">
                {t.assertions.map((a, i) => (
                  <li key={i}>
                    <div>
                      <span className={a.passed ? "text-good" : "text-bad"}>
                        {a.passed ? "✓ " : "✗ "}
                      </span>
                      {explainAssertion(a)}
                    </div>
                    {a.detail && (
                      <div className="pl-4 text-xs text-slate-500">
                        {a.type}: {a.detail}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <details className="mt-2 text-xs text-slate-400">
              <summary className="cursor-pointer">model's actual response</summary>
              <pre className="mt-1 whitespace-pre-wrap break-words text-slate-300">
                {t.actual || t.error || "(empty)"}
              </pre>
            </details>
          </div>
        ))}
      </div>
    </div>
  );
}
