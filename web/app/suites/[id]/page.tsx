"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  compareRuns,
  getRunStatus,
  getRunSummary,
  getSuite,
  listRuns,
  RunDoc,
  RunSummary,
  setBaseline,
  startRun,
  SuiteDoc,
} from "@/lib/api";
import { RequireAuth } from "@/components/AuthProvider";
import ComparisonReport, {
  Comparison,
} from "@/components/ComparisonReport";
import { Panel, Rule, Status } from "@/components/ui";
import { JudgeFloorLine, ResolutionLine } from "@/components/BenchmarkLines";

const TERMINAL = new Set(["completed", "failed"]);

function stateOf(s: string) {
  if (s === "completed") return "pass" as const;
  if (s === "failed") return "fail" as const;
  return "pending" as const;
}

function SuiteDetail({ id }: { id: string }) {
  const [suite, setSuite] = useState<SuiteDoc | null>(null);
  const [runs, setRuns] = useState<RunDoc[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>("");
  const [comparing, setComparing] = useState<string | null>(null);
  const [report, setReport] = useState<{
    baseline: RunSummary;
    candidate: RunSummary;
    comparison: Comparison;
    runId: string;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([getSuite(id), listRuns(id)]);
      setSuite(s);
      setRuns(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  /* A run started elsewhere — the workbench, the CLI — is in this list
     too. While any run here is in flight, reload the list every few
     seconds so its row moves; "0/19 scored" for the whole run was this
     page's snapshot, not the run. */
  const inFlight = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!inFlight) return;
    const iv = setInterval(load, 3000);
    return () => clearInterval(iv);
  }, [inFlight, load]);

  /* Poll while a run we started is in flight. */
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await getRunStatus(active);
        if (!alive) return;
        setProgress(
          `${s.status} ${s.completed_tests}/${s.total_tests}` +
            (s.queue_position ? ` · queued #${s.queue_position}` : "")
        );
        if (TERMINAL.has(s.status)) {
          setActive(null);
          setProgress("");
          load();
        }
      } catch {
        if (alive) setActive(null);
      }
    };
    const iv = setInterval(tick, 1000);
    tick();
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [active, load]);

  async function run() {
    setError(null);
    try {
      const { run_id } = await startRun(id);
      setActive(run_id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function promote(runId: string) {
    setError(null);
    try {
      await setBaseline(id, runId);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  /* The whole point of promoting a baseline: check a later run against
     it and get the paired statistics, not just two pass rates. */
  const compare = useCallback(
    async (runId: string) => {
      const base = suite?.baseline_run_id;
      if (!base) return;
      setError(null);
      setComparing(runId);
      setReport(null);
      try {
        const [baseline, candidate, comparison] = await Promise.all([
          getRunSummary(base),
          getRunSummary(runId),
          compareRuns(base, runId),
        ]);
        setReport({ baseline, candidate, comparison, runId });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setComparing(null);
      }
    },
    [suite?.baseline_run_id]
  );

  if (error && !suite) {
    return (
      <div className="panel border-error p-4 text-sm text-error">{error}</div>
    );
  }
  if (!suite) return <p className="font-mono text-sm text-muted">loading…</p>;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <p className="label-xs">
            <Link href="/suites" className="hover:text-text">
              § Benchmarks
            </Link>{" "}
            / {suite.name}
          </p>
          <h1 className="font-display text-3xl">{suite.name}</h1>
          {suite.description && (
            <p className="max-w-2xl text-sm leading-relaxed text-muted">
              {suite.description}
            </p>
          )}
          <p className="font-mono text-xs text-muted">
            {suite.provider ?? "ollama"} / {suite.model} ·{" "}
            {suite.tests?.length ?? 0} tests · {suite.evaluator}
          </p>
          <div className="space-y-0.5 pt-1">
            <ResolutionLine r={suite.resolution} />
            <JudgeFloorLine f={suite.judge_floor} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          {progress && (
            <span className="font-mono text-xs text-accent">{progress}</span>
          )}
          <button
            className="btn btn-primary"
            onClick={run}
            disabled={!!active}
          >
            {active ? "Running…" : "Run benchmark"}
          </button>
        </div>
      </header>

      {error && (
        <div className="panel border-error p-3 text-sm text-error">{error}</div>
      )}

      {suite.baseline_run_id && (
        <p className="font-mono text-xs text-muted">
          baseline ={" "}
          <Link
            href={`/runs/${suite.baseline_run_id}`}
            className="text-accent hover:underline"
          >
            {suite.baseline_run_id}
          </Link>
        </p>
      )}

      {report && (
        <section className="space-y-3">
          <Rule label="Comparison" />
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="font-mono text-xs text-muted">
              baseline {suite.baseline_run_id?.slice(-8)} → run{" "}
              {report.runId.slice(-8)}
            </p>
            <button
              className="btn btn-ghost px-2 py-1 font-mono text-[11px]"
              onClick={() => setReport(null)}
            >
              close
            </button>
          </div>
          <ComparisonReport
            baseline={report.baseline}
            candidate={report.candidate}
            comparison={report.comparison}
          />
        </section>
      )}

      <Rule label="Run history" />

      {runs.length === 0 && (
        <Panel>
          <p className="text-sm text-muted">
            No runs yet. Hit “Run benchmark” to create the first one.
          </p>
        </Panel>
      )}

      <div className="space-y-2">
        {runs.map((r) => {
          const isBaseline = suite.baseline_run_id === r._id;
          return (
            <div
              key={r._id}
              className="panel flex flex-wrap items-center justify-between gap-3 p-3"
            >
              {/* A run is identified by what it found and when, not by the
                  tail of its Mongo id — and the way in says so in words.
                  The id stays visible for copying into the CLI. */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <Status state={stateOf(r.status)}>{r.status}</Status>
                <span className="font-mono text-sm tnum">
                  {typeof r.pass_rate === "number" ? (
                    <>
                      <span className="text-text">
                        {(r.pass_rate * 100).toFixed(1)}%
                      </span>
                      <span className="text-muted"> passed</span>
                    </>
                  ) : (
                    <span className="text-muted">not scored</span>
                  )}
                </span>
                <span className="font-mono text-[11px] text-muted tnum">
                  {r.status === "queued" || r.status === "running"
                    ? `${r.completed_tests ?? 0}/${r.total_tests} answered`
                    : `${r.scored_tests ?? r.completed_tests}/${r.total_tests} scored`}
                  {r.created_at
                    ? ` · ${r.created_at.slice(0, 16).replace("T", " ")}`
                    : ""}
                </span>
                {!!r.rate_limited_samples && (
                  <span
                    className="font-mono text-[11px] text-warning"
                    title="Samples dropped to provider rate limits. Those tests were scored on fewer samples than requested."
                  >
                    {r.rate_limited_samples} samples lost
                  </span>
                )}
                <Link
                  href={`/runs/${r._id}`}
                  className="font-mono text-xs text-accent hover:underline"
                >
                  Open report →
                </Link>
                <span className="font-mono text-[10px] text-muted/60">
                  {r._id.slice(-8)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {isBaseline ? (
                  <Status state="pass">baseline</Status>
                ) : (
                  r.status === "completed" && (
                    <>
                      {suite.baseline_run_id && (
                        <button
                          className="btn btn-ghost px-2 py-1 font-mono text-[11px]"
                          onClick={() => compare(r._id)}
                          disabled={comparing === r._id}
                        >
                          {comparing === r._id
                            ? "comparing…"
                            : "compare to baseline"}
                        </button>
                      )}
                      <button
                        className="btn btn-ghost px-2 py-1 font-mono text-[11px]"
                        onClick={() => promote(r._id)}
                      >
                        set as baseline
                      </button>
                    </>
                  )
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Page() {
  const params = useParams<{ id: string }>();
  return (
    <RequireAuth>
      <SuiteDetail id={params.id} />
    </RequireAuth>
  );
}
