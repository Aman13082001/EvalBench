"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BenchmarkChoice,
  BenchmarkPicker,
  isHosted,
  modelReady,
  serverKeyBlocked,
  toRunOptions,
  KeyMode,
  KeyPicker,
  ModelChoice,
  ModelPicker,
  resolveBenchmark,
  useBenchmarks,
  useQuota,
} from "./pickers";
import { RunProgress, useRun } from "./useRun";

/* ── §4 · Compare two models ────────────────────────────────────
   Same benchmark, two models, both runs through the normal job path,
   then the existing regression engine pairs the results by test name.
   Nothing new is computed here; the page just runs it twice and hands
   the two run ids to /compare. */

export default function CompareModels({
  benchmarks,
  quota: quotaState,
}: {
  benchmarks: ReturnType<typeof useBenchmarks>;
  quota: ReturnType<typeof useQuota>;
}) {
  const router = useRouter();
  const { bundled, mine } = benchmarks;
  const { quota, refresh: refreshQuota } = quotaState;

  const [bench, setBench] = useState<BenchmarkChoice | null>(null);
  const [a, setA] = useState<ModelChoice>({ provider: "groq", model: "" });
  const [b, setB] = useState<ModelChoice>({ provider: "groq", model: "" });
  const [keyMode, setKeyMode] = useState<KeyMode>({ own: false, key: "" });
  const [err, setErr] = useState<string | null>(null);

  const runA = useRun("cmp-a");
  const runB = useRun("cmp-b");
  const busy =
    ["starting", "running"].includes(runA.state.phase) ||
    ["starting", "running"].includes(runB.state.phase);

  const hosted = isHosted(a.provider) || isHosted(b.provider);
  // A comparison is two runs: twice the calls against the day, and each
  // run on its own against the per-run ceiling.
  const cost = bench?.calls;
  const blockedBy =
    hosted && !keyMode.own
      ? (serverKeyBlocked(cost, quota) ??
        (cost != null && quota?.remaining != null && cost * 2 > quota.remaining
          ? `two runs need ${cost * 2} calls · ${quota.remaining} left today on EvalBench's key`
          : null))
      : null;
  const capBlocks = blockedBy !== null;

  const canRun =
    !!bench &&
    modelReady(a) &&
    modelReady(b) &&
    !(a.provider === b.provider && a.model === b.model && a.baseUrl === b.baseUrl) &&
    (!hosted || !keyMode.own || keyMode.key.length > 0) &&
    !capBlocks &&
    !busy;

  async function go() {
    if (!bench) return;
    setErr(null);
    let suite: { id: string; name: string };
    try {
      suite = await resolveBenchmark(bench);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return;
    }
    const key = keyMode.own ? keyMode.key : undefined;
    // both in parallel — the worker queue handles the rest
    await Promise.all([
      runA.run(suite.id, toRunOptions(a, key), { suiteName: suite.name, model: a.model, provider: a.provider }),
      runB.run(suite.id, toRunOptions(b, key), { suiteName: suite.name, model: b.model, provider: b.provider }),
    ]);
    refreshQuota();
    if (bench.kind !== "mine") benchmarks.reload();
  }

  /* Both landed — whether this mount started them or resumed them after
     a trip to another page — so open the comparison. Forgotten first:
     coming back to the workbench must not open it again. */
  useEffect(() => {
    if (runA.state.phase === "done" && runB.state.phase === "done") {
      const a = runA.state.runId, b = runB.state.runId;
      runA.reset();
      runB.reset();
      router.push(`/compare?a=${a}&b=${b}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runA.state.phase, runB.state.phase]);

  return (
    <div className="panel space-y-4 p-4">
      <div className="space-y-1">
        <p className="font-display text-lg leading-none">Compare two models</p>
        <p className="text-sm text-muted">
          Which one actually performs better on the same benchmark — and
          whether the gap is real or inside the noise.
        </p>
      </div>

      <div className="space-y-2">
        <label className="label-xs block" htmlFor="cmp-benchmark">
          Benchmark
        </label>
        <BenchmarkPicker
          id="cmp-benchmark"
          value={bench}
          onChange={setBench}
          bundled={bundled}
          mine={mine}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <span className="label-xs block">Model A</span>
          <ModelPicker value={a} onChange={setA} idPrefix="cmp-a" />
          <RunProgress state={runA.state} />
          {runA.state.phase === "failed" && (
            <p className="text-xs text-error">{runA.state.error}</p>
          )}
        </div>
        <div className="space-y-2">
          <span className="label-xs block">Model B</span>
          <ModelPicker value={b} onChange={setB} idPrefix="cmp-b" />
          <RunProgress state={runB.state} />
          {runB.state.phase === "failed" && (
            <p className="text-xs text-error">{runB.state.error}</p>
          )}
        </div>
      </div>

      {hosted && (
        <KeyPicker
          value={keyMode}
          onChange={setKeyMode}
          quota={quota}
          provider={isHosted(a.provider) ? a.provider : b.provider}
          name="cmp-keymode"
          cost={cost}
        />
      )}
      {capBlocks && (
        <p className="text-xs text-warning">
          A comparison is two runs: {blockedBy}. Add your own key, or wait for
          tomorrow&rsquo;s allowance.
        </p>
      )}
      {a.model && a.model === b.model && a.provider === b.provider && (
        <p className="text-xs text-warning">Pick two different models.</p>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <button className="btn btn-primary" onClick={go} disabled={!canRun}>
          {busy ? "Running both…" : "Compare"}
        </button>
        {bench && (
          <span className="font-mono text-[11px] text-muted tnum">
            {bench.tests} tests × 2 models
          </span>
        )}
      </div>
      {err && <p className="text-xs text-error">{err}</p>}
    </div>
  );
}
