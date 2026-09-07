"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import yaml from "js-yaml";
import {
  getPlaygroundInfo,
  getPlaygroundRun,
  PlaygroundInfo,
  runPlayground,
  RunSummary,
} from "@/lib/api";
import { EXAMPLE_SUITE } from "@/lib/example";
import { PRESETS } from "@/lib/presets";
import Results from "@/components/Results";

function RunPage() {
  const params = useSearchParams();
  const permalinkId = params.get("id");

  const [text, setText] = useState(EXAMPLE_SUITE);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunSummary | null>(null);
  const [info, setInfo] = useState<PlaygroundInfo | null>(null);

  /* Limits and the provider list come from the API. Hardcoding them in
     the copy here means they silently go stale when the server changes. */
  useEffect(() => {
    getPlaygroundInfo()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

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
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="label-xs">§ Playground</p>
        <h1 className="font-display text-3xl">Run an evaluation</h1>
        <p className="max-w-2xl text-sm text-muted">
          Your key, your models, nothing stored.
          {info
            ? ` Capped at ${info.max_tests} tests and ${info.max_samples} samples;`
            : " Capped;"}{" "}
          results expire after 24 hours.
        </p>
        {info && (
          <p className="font-mono text-[11px] text-muted">
            providers: {info.providers.join(" · ")}
          </p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="label-xs" htmlFor="suite">
              Suite definition (YAML)
            </label>
            <div className="flex flex-wrap gap-1">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  title={p.blurb}
                  onClick={() => {
                    setText(p.yaml);
                    setResult(null);
                    setError(null);
                  }}
                  className="border border-line px-2 py-0.5 font-mono text-[11px] text-muted transition-colors hover:border-primary hover:text-text"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <textarea
            id="suite"
            className="field h-[26rem] resize-y font-mono text-xs leading-relaxed"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {info && (
            <p className="font-mono text-[11px] leading-relaxed text-muted">
              <span className="text-text">assert types:</span>{" "}
              {info.assertion_types.join(" · ")}
            </p>
          )}
          <input
            className="field font-mono text-xs"
            type="password"
            placeholder="provider API key — never stored"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <div className="flex items-center gap-3">
            <button className="btn btn-primary" onClick={run} disabled={busy}>
              {busy ? "Running…" : "Run suite"}
            </button>
            {result && (
              <a
                className="font-mono text-xs text-accent hover:underline"
                href={`/run?id=${result.run_id}`}
              >
                permalink
              </a>
            )}
          </div>
          <p className="text-xs text-muted">
            Free key, no card:{" "}
            <a className="text-accent hover:underline" href="https://console.groq.com">
              console.groq.com
            </a>
          </p>
        </div>

        <div>
          {error && (
            <div className="panel border-error p-4 text-sm text-error">
              {error}
            </div>
          )}
          {!error && !result && !busy && (
            <div className="panel p-6 text-sm text-muted">
              Results will appear here.
            </div>
          )}
          {busy && !result && (
            <div className="panel p-6 font-mono text-sm text-muted">
              measuring…
            </div>
          )}
          {result && <Results r={result} />}
        </div>
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
