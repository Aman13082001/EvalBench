"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { listRecentRuns, RecentRun } from "@/lib/api";
import Results from "@/components/Results";
import { Panel, Rule } from "@/components/ui";
import {
  BenchmarkChoice,
  BenchmarkPicker,
  isHosted,
  KeyMode,
  KeyPicker,
  ModelChoice,
  ModelPicker,
  resolveBenchmark,
  useBenchmarks,
  useQuota,
} from "./pickers";
import { RunProgress, useRun } from "./useRun";

/* ── §1 · Run an evaluation ─────────────────────────────────────
   The primary section. Select a benchmark, select a model, run it,
   read the result. Everything here talks to endpoints that already
   existed; the only new ones are the quota and the benchmark list. */

export default function RunEvaluation({
  benchmarks,
  quota: quotaState,
}: {
  benchmarks: ReturnType<typeof useBenchmarks>;
  quota: ReturnType<typeof useQuota>;
}) {
  const { bundled, mine, error: benchErr } = benchmarks;
  const { quota, refresh: refreshQuota } = quotaState;

  const [bench, setBench] = useState<BenchmarkChoice | null>(null);
  const [model, setModel] = useState<ModelChoice>({ provider: "groq", model: "" });
  const [keyMode, setKeyMode] = useState<KeyMode>({ own: false, key: "" });
  const [recent, setRecent] = useState<RecentRun[]>([]);
  const [suiteName, setSuiteName] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  const { state, run, reset } = useRun();

  /* Follow the benchmark's own model until the user picks one. */
  useEffect(() => {
    if (bench && !model.model && bench.model) {
      setModel({ provider: bench.provider || "groq", model: bench.model });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bench]);

  useEffect(() => {
    listRecentRuns(50).then(setRecent).catch(() => setRecent([]));
  }, [state.phase]);

  /* Cost line: real figures or a clear absence. Token counts are not
     known before a run, so the only honest pre-run number is what the
     same benchmark cost on the same model last time. */
  const costLine = useMemo(() => {
    if (!bench) return null;
    const tests = bench.tests;
    const prior = recent.find(
      (r) =>
        r.status === "completed" &&
        r.model === model.model &&
        (bench.kind === "mine" ? r.suite_id === bench.id : true) &&
        r.total_tests === tests
    );
    const base = `${tests} tests`;
    if (!isHosted(model.provider)) return `${base} · local model, nothing spent`;
    if (prior && prior.total_cost_usd > 0)
      return `${base} · last run on ${model.model} cost $${prior.total_cost_usd.toFixed(4)}`;
    return `${base} · cost known after the first run on this model`;
  }, [bench, model, recent]);

  const canRun =
    !!bench &&
    !!model.model &&
    (!isHosted(model.provider) || !keyMode.own || keyMode.key.length > 0) &&
    !(isHosted(model.provider) && !keyMode.own && quota?.remaining === 0) &&
    state.phase !== "starting" &&
    state.phase !== "running";

  async function go() {
    if (!bench) return;
    setErr(null);
    reset();
    let resolved: { id: string; name: string };
    try {
      resolved = await resolveBenchmark(bench);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return;
    }
    setSuiteName(resolved.name);
    await run(resolved.id, {
      model: model.model,
      provider: model.provider,
      provider_key: keyMode.own ? keyMode.key : undefined,
    });
    refreshQuota();
    if (bench.kind !== "mine") benchmarks.reload();
  }

  return (
    <section className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-2">
          <label className="label-xs block" htmlFor="benchmark">
            Benchmark
          </label>
          <BenchmarkPicker
            value={bench}
            onChange={(c) => {
              setBench(c);
              setErr(null);
            }}
            bundled={bundled}
            mine={mine}
          />
          {benchErr && <p className="text-xs text-error">{benchErr}</p>}
        </div>

        <div className="space-y-2">
          <span className="label-xs block">Model</span>
          <ModelPicker value={model} onChange={setModel} idPrefix="eval" />
          <KeyPicker
            value={keyMode}
            onChange={setKeyMode}
            quota={quota}
            provider={model.provider}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <button className="btn btn-primary" onClick={go} disabled={!canRun}>
          {state.phase === "starting" || state.phase === "running"
            ? "Running…"
            : "Run evaluation"}
        </button>
        <RunProgress state={state} />
        {costLine && (
          <span className="font-mono text-[11px] text-muted tnum">{costLine}</span>
        )}
      </div>

      {err && (
        <div className="panel border-error p-3 text-sm text-error">{err}</div>
      )}
      {state.phase === "failed" && (
        <div className="panel border-error p-3 text-sm text-error">
          {state.error}
          {state.runId && (
            <span className="ml-2 font-mono text-[11px] text-muted">
              run {state.runId.slice(-8)}
            </span>
          )}
        </div>
      )}

      {/* ── §2 · The result ─────────────────────────────────── */}
      {state.phase === "done" && (
        <div className="space-y-5">
          <Rule label="§2 · Result" />
          <ResultHeader
            model={state.summary.model}
            suite={suiteName || bench?.label || ""}
            summary={state.summary}
            runId={state.runId}
          />
          <Results r={state.summary} />
        </div>
      )}

      {state.phase !== "done" && (
        <div className="space-y-5">
          <Rule label="§2 · Result" />
          <Panel>
            <p className="text-sm text-muted">
              {state.phase === "idle"
                ? "Pick a benchmark and a model above. The result appears here — the verdict first, then every number behind it, then each test."
                : state.phase === "failed"
                  ? "The run did not complete. The error is above."
                  : "Running — the result will appear here when every test has been scored."}
            </p>
          </Panel>
        </div>
      )}
    </section>
  );
}

/** The one thing the page must make obvious: how did this model do on
 *  this benchmark. Big number, then the two names, then the permalink. */
function ResultHeader({
  model,
  suite,
  summary,
  runId,
}: {
  model: string;
  suite: string;
  summary: { pass_rate: number; passed: number; scored_tests: number };
  runId: string;
}) {
  const pct = (summary.pass_rate * 100).toFixed(1);
  return (
    <div className="panel flex flex-wrap items-end justify-between gap-4 p-5">
      <div className="space-y-1">
        <p className="label-xs">
          <span className="font-mono text-text">{model}</span> on{" "}
          <span className="font-mono text-text">{suite}</span>
        </p>
        <p className="font-display text-5xl leading-none tnum">
          {pct}
          <span className="text-2xl text-muted">%</span>
        </p>
        <p className="font-mono text-xs text-muted tnum">
          {summary.passed} of {summary.scored_tests} tests passed every check
        </p>
      </div>
      <Link
        href={`/runs/${runId}`}
        className="font-mono text-[11px] text-accent hover:underline"
      >
        permalink →
      </Link>
    </div>
  );
}
