import { RunSummary } from "@/lib/api";

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

function ci(pair: [number, number] | null): string {
  if (!pair) return "";
  return ` [${pct(pair[0])}–${pct(pair[1])}]`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-xl font-bold">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export default function Results({ r }: { r: RunSummary }) {
  const cats = Object.entries(r.by_category);
  const atypes = Object.entries(r.assertion_types);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Pass rate"
          value={pct(r.pass_rate)}
          sub={`${r.passed}/${r.scored_tests}${ci(r.pass_rate_ci)}`}
        />
        <Stat label="Avg score" value={r.avg_score.toFixed(3)} />
        <Stat
          label="Est. cost"
          value={r.total_cost_usd ? `$${r.total_cost_usd.toFixed(5)}` : "$0"}
          sub={`${r.total_prompt_tokens}/${r.total_completion_tokens} tok`}
        />
        <Stat label="Avg latency" value={`${Math.round(r.avg_latency_ms)} ms`} />
      </div>

      {(r.errors > 0 || r.rate_limited_samples > 0) && (
        <p className="text-sm text-warn">
          {r.errors > 0 && `${r.errors} test(s) errored. `}
          {r.rate_limited_samples > 0 &&
            `${r.rate_limited_samples} sample(s) rate-limited.`}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {cats.length > 1 && (
          <div className="card p-3">
            <h3 className="mb-2 text-sm font-semibold">By category</h3>
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
            <h3 className="mb-2 text-sm font-semibold">Assertion checks</h3>
            <table className="w-full text-sm">
              <tbody>
                {atypes.map(([t, c]) => (
                  <tr key={t} className="border-t border-line/50">
                    <td className="py-1">{t}</td>
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
              <ul className="mt-2 space-y-0.5 text-xs">
                {t.assertions.map((a, i) => (
                  <li key={i}>
                    <span className={a.passed ? "text-good" : "text-bad"}>
                      {a.passed ? "ok " : "xx "}
                    </span>
                    <span className="text-slate-300">{a.type}</span>{" "}
                    <span className="text-slate-500">{a.detail}</span>
                  </li>
                ))}
              </ul>
            )}
            <details className="mt-2 text-xs text-slate-400">
              <summary className="cursor-pointer">response</summary>
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
