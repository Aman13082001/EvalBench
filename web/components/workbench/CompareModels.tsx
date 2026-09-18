"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  BenchmarkChoice,
  BenchmarkPicker,
  isHosted,
  modelReady,
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

  const runA = useRun();
  const runB = useRun();
  const busy =
    ["starting", "running"].includes(runA.state.phase) ||
    ["starting", "running"].includes(runB.state.phase);

  const hosted = isHosted(a.provider) || isHosted(b.provider);
  // two runs on the server key means two against the cap
  const capBlocks = hosted && !keyMode.own && (quota?.remaining ?? 99) < 2;

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
    const [sa, sb] = await Promise.all([
      runA.run(suite.id, toRunOptions(a, key)),
      runB.run(suite.id, toRunOptions(b, key)),
    ]);
    refreshQuota();
    if (bench.kind !== "mine") benchmarks.reload();
    if (sa && sb) {
      router.push(`/compare?a=${sa.run_id}&b=${sb.run_id}`);
    }
  }

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
        />
      )}
      {capBlocks && (
        <p className="text-xs text-warning">
          A comparison is two runs. Add your own key, or wait for tomorrow&rsquo;s
          allowance.
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
