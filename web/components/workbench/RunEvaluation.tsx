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
  modelReady,
  needsUrl,
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
import { AnswersPicker, AnswersState } from "./AnswersPicker";
import { endpointHost } from "@/lib/api";

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
  /* Where the answers come from. "model": EvalBench calls one. "answers":
     the visitor already has them — nothing is generated, and only the
     checks that ask an LLM to grade need a model at all. */
  const [source, setSource] = useState<"model" | "answers">("model");
  const [answers, setAnswers] = useState<AnswersState | null>(null);
  const [judge, setJudge] = useState<ModelChoice>({ provider: "groq", model: "" });
  const [judgeKey, setJudgeKey] = useState<KeyMode>({ own: false, key: "" });
  // Undefined = unknown; show the grader rather than assume it is not needed.
  const needsJudge = bench?.needsJudge !== false;
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
    if (source === "answers") {
      if (!answers) return `${tests} tests · nothing is generated`;
      if (!needsJudge) return `${answers.rows.length} answers · no model is called at all`;
      return `${answers.rows.length} answers · only the grader is called`;
    }
    const prior = recent.find(
      (r) =>
        r.status === "completed" &&
        r.model === model.model &&
        (bench.kind === "mine" ? r.suite_id === bench.id : true) &&
        r.total_tests === tests
    );
    const base = `${tests} tests`;
    if (needsUrl(model.provider)) return `${base} · your endpoint, nothing of ours is spent`;
    if (!isHosted(model.provider)) return `${base} · local model, nothing spent`;
    if (prior && prior.total_cost_usd > 0)
      return `${base} · last run on ${model.model} cost $${prior.total_cost_usd.toFixed(4)}`;
    return `${base} · cost known after the first run on this model`;
  }, [bench, model, recent, source, answers, needsJudge]);

  const graderOk =
    !needsJudge ||
    (modelReady(judge) &&
      (!isHosted(judge.provider) || !judgeKey.own || judgeKey.key.length > 0) &&
      !(isHosted(judge.provider) && !judgeKey.own && quota?.remaining === 0));

  const canRun =
    !!bench &&
    (source === "answers"
      ? !!answers && answers.rows.length > 0 && graderOk
      : modelReady(model) &&
        (!isHosted(model.provider) || !keyMode.own || keyMode.key.length > 0) &&
        !(isHosted(model.provider) && !keyMode.own && quota?.remaining === 0)) &&
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
    await run(
      resolved.id,
      source === "answers" && answers
        ? (() => {
            // The grader is a model choice like any other; a custom
            // endpoint carries its URL and key inside it.
            const g = needsJudge ? toRunOptions(judge, judgeKey.own ? judgeKey.key : undefined) : {};
            return {
              answers: answers.rows,
              model: answers.label || undefined,
              judge_provider: g.provider,
              judge_model: g.model,
              provider_key: g.provider_key,
              base_url: g.base_url,
            };
          })()
        : toRunOptions(model, keyMode.own ? keyMode.key : undefined)
    );
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

        <div className="space-y-3">
          {/* Answers from a model, or answers you already have. The
              second is the path with no key and no endpoint: the file is
              replayed, and the checks run on it exactly as they would on
              a live answer. */}
          <div className="flex items-baseline justify-between gap-3">
            <span className="label-xs block">Answers from</span>
            <div className="flex gap-1" role="tablist" aria-label="Where the answers come from">
              {(["model", "answers"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  role="tab"
                  aria-selected={source === s}
                  onClick={() => setSource(s)}
                  className={`btn px-2 py-1 font-mono text-[11px] ${
                    source === s ? "btn-primary" : "btn-ghost"
                  }`}
                >
                  {s === "model" ? "a model" : "answers I have"}
                </button>
              ))}
            </div>
          </div>

          {source === "model" ? (
            <>
              <ModelPicker value={model} onChange={setModel} idPrefix="eval" />
              <KeyPicker
                value={keyMode}
                onChange={setKeyMode}
                quota={quota}
                provider={model.provider}
              />
            </>
          ) : (
            <>
              <AnswersPicker
                value={answers}
                onChange={setAnswers}
                expectedTests={bench?.tests}
                bench={bench}
              />
              {needsJudge && (
                <div className="space-y-2 border-t border-line pt-3">
                  <p className="label-xs">
                    Grader{" "}
                    <span className="normal-case text-muted">
                      — {bench?.needsJudge === undefined
                        ? "used only if this benchmark has checks that ask a model to grade"
                        : "this benchmark has checks that ask a model to grade the answers"}
                    </span>
                  </p>
                  <ModelPicker value={judge} onChange={setJudge} idPrefix="judge" />
                  <KeyPicker
                    value={judgeKey}
                    onChange={setJudgeKey}
                    quota={quota}
                    provider={judge.provider}
                    name="judge-keymode"
                  />
                </div>
              )}
              {!needsJudge && (
                <p className="text-xs text-muted">
                  Every check in this benchmark scores without a model — string,
                  schema and semantic checks only. Nothing is called and nothing
                  is spent.
                </p>
              )}
            </>
          )}
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
                ? source === "answers"
                  ? "Pick a benchmark and upload the answers above. Nothing is generated; the checks run on what you gave them."
                  : "Pick a benchmark and a model above. The result appears here — the verdict first, then every number behind it, then each test."
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
  summary: {
    pass_rate: number | null;
    passed: number;
    scored_tests: number;
    total_tests: number;
    errors: number;
    base_url?: string | null;
  };
  runId: string;
}) {
  // Null when nothing scored — the big number then reads "—",
  // which is the honest answer rather than a confident 0.0%.
  const pct =
    summary.pass_rate == null ? null : (summary.pass_rate * 100).toFixed(1);
  const partial = summary.errors > 0;
  // A custom run is "this model, at that endpoint". Name the host: the
  // same model name means different things on different servers.
  const at = endpointHost(summary.base_url);
  return (
    <div className="panel flex flex-wrap items-end justify-between gap-4 p-5">
      <div className="space-y-1">
        <p className="label-xs">
          <span className="font-mono text-text">{model}</span>
          {at && (
            <>
              {" "}at <span className="font-mono text-text">{at}</span>
            </>
          )}{" "}
          on <span className="font-mono text-text">{suite}</span>
        </p>
        <p className="font-display text-5xl leading-none tnum">
          {pct ?? "—"}
          {pct !== null && <span className="text-2xl text-muted">%</span>}
        </p>
        {/* The qualifier lives next to the big number, not three panels
            down. A 93.8% over 16 of 51 tests is a different finding from
            a 93.8% over 51, and the reader must not have to hunt for that. */}
        <p className="font-mono text-xs text-muted tnum">
          {summary.passed} of {summary.scored_tests} tests passed every check
          {partial && (
            <span className="text-warning">
              {" "}· {summary.errors} of {summary.total_tests} never got an answer
            </span>
          )}
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
