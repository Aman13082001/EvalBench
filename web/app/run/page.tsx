"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import yaml from "js-yaml";
import {
  getPlaygroundRun,
  runPlayground,
  RunSummary,
} from "@/lib/api";
import { EXAMPLE_SUITE } from "@/lib/example";
import Results from "@/components/Results";

function RunPage() {
  const params = useSearchParams();
  const permalinkId = params.get("id");

  const [text, setText] = useState(EXAMPLE_SUITE);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunSummary | null>(null);

  useEffect(() => {
    if (!permalinkId) return;
    setBusy(true);
    getPlaygroundRun(permalinkId)
      .then((r) => setResult(r))
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  }, [permalinkId]);

  const run = useCallback(async () => {
    setError(null);
    setResult(null);
    let suite: unknown;
    try {
      suite = yaml.load(text);
    } catch (e) {
      setError(`YAML parse error: ${e}`);
      return;
    }
    setBusy(true);
    try {
      const r = await runPlayground(suite, key);
      setResult(r);
      window.history.replaceState(null, "", `/run?id=${r.run_id}`);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }, [text, key]);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-3">
        <label className="block text-sm font-semibold">Suite (YAML)</label>
        <textarea
          className="field h-[28rem] resize-y font-mono text-xs leading-relaxed"
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <input
          className="field"
          type="password"
          placeholder="Your provider API key (e.g. free Groq key) — not stored"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <button className="btn" onClick={run} disabled={busy}>
            {busy ? "Running…" : "Run suite"}
          </button>
          {result && (
            <a
              className="text-sm text-accent hover:underline"
              href={`/run?id=${result.run_id}`}
            >
              permalink
            </a>
          )}
        </div>
        <p className="text-xs text-slate-500">
          Get a free key at console.groq.com (no card). Capped at 12 tests, 3
          samples. Results expire after 24h.
        </p>
      </div>

      <div>
        {error && (
          <div className="card border-bad p-3 text-sm text-bad">{error}</div>
        )}
        {!error && !result && !busy && (
          <div className="card p-6 text-sm text-slate-400">
            Results will appear here.
          </div>
        )}
        {busy && !result && (
          <div className="card p-6 text-sm text-slate-400">Running…</div>
        )}
        {result && <Results r={result} />}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className="text-slate-400">Loading…</div>}>
      <RunPage />
    </Suspense>
  );
}
