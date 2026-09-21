"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getRunStatus,
  getRunSummary,
  RunOptions,
  RunStatus,
  RunSummary,
  startRun,
} from "@/lib/api";

/* Start a run against the existing job endpoint and poll the existing
   status endpoint until it settles. One implementation, used by the
   single-model evaluation and by each side of a model comparison, so
   the two cannot drift.

   A run outlives the page. Someone starts a nineteen-test benchmark,
   goes to look at the Benchmarks page, comes back — and the form was
   blank, the run still going somewhere behind it. So a hook with a
   `slot` remembers its run in the tab (sessionStorage: this tab, this
   sign-in, gone when the tab closes) and on the next mount picks the
   polling back up where it left off, through to the finished report.
   A run the API no longer serves — another account's, a cleared
   database — is forgotten quietly rather than shown as an error. */

export type RunState =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "running"; runId: string; status: RunStatus }
  | { phase: "done"; runId: string; summary: RunSummary }
  | { phase: "failed"; runId?: string; error: string };

/* What the page needs to show a resumed run that its form no longer
   knows about: the benchmark's name, the model. */
export type RunMeta = { suiteName?: string; model?: string; provider?: string };

const POLL_MS = 1500;
const STORE = "eb-run:";

function recall(slot: string): { runId: string; meta: RunMeta } | null {
  try {
    const raw = sessionStorage.getItem(STORE + slot);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function remember(slot: string | undefined, runId: string, meta: RunMeta) {
  if (!slot) return;
  try {
    sessionStorage.setItem(STORE + slot, JSON.stringify({ runId, meta }));
  } catch {
    /* private mode: the run simply is not resumable */
  }
}

function forget(slot: string | undefined) {
  if (!slot) return;
  try {
    sessionStorage.removeItem(STORE + slot);
  } catch {
    /* nothing to forget */
  }
}

export function useRun(slot?: string) {
  const [state, setState] = useState<RunState>({ phase: "idle" });
  const [meta, setMeta] = useState<RunMeta>({});
  const alive = useRef(true);

  /* Poll until terminal. `resumed` runs forget a run the API refuses
     instead of reporting it: the form has nothing to say about a run it
     did not start in this life. */
  const poll = useCallback(
    async (runId: string, resumed = false): Promise<RunSummary | null> => {
      while (alive.current) {
        let s: RunStatus;
        try {
          s = await getRunStatus(runId);
        } catch (e) {
          if (resumed) {
            forget(slot);
            setState({ phase: "idle" });
            return null;
          }
          setState({
            phase: "failed",
            runId,
            error: e instanceof Error ? e.message : String(e),
          });
          return null;
        }
        if (s.status === "completed") {
          try {
            const summary = await getRunSummary(runId);
            setState({ phase: "done", runId, summary });
            return summary;
          } catch (e) {
            setState({
              phase: "failed",
              runId,
              error: e instanceof Error ? e.message : String(e),
            });
            return null;
          }
        }
        if (s.status === "failed") {
          setState({
            phase: "failed",
            runId,
            error: s.error || "The run failed without a message.",
          });
          return null;
        }
        setState({ phase: "running", runId, status: s });
        await new Promise((res) => setTimeout(res, POLL_MS));
      }
      return null;
    },
    [slot]
  );

  const run = useCallback(
    async (suiteId: string, opts: RunOptions, m: RunMeta = {}): Promise<RunSummary | null> => {
      alive.current = true;
      setMeta(m);
      setState({ phase: "starting" });
      let runId: string;
      try {
        const r = await startRun(suiteId, opts);
        runId = r.run_id;
      } catch (e) {
        setState({
          phase: "failed",
          error: e instanceof Error ? e.message : String(e),
        });
        return null;
      }
      remember(slot, runId, m);
      return poll(runId);
    },
    [slot, poll]
  );

  /* Pick up a run this tab left in flight, or the report it reached. */
  useEffect(() => {
    if (!slot) return;
    const saved = recall(slot);
    if (!saved) return;
    alive.current = true;
    setMeta(saved.meta || {});
    setState({
      phase: "running",
      runId: saved.runId,
      status: { run_id: saved.runId, status: "queued", progress: 0, completed_tests: 0, total_tests: 0, error: null },
    });
    poll(saved.runId, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slot]);

  /* Leaving the page stops this poll; the stored id lets the next mount
     start its own. */
  useEffect(
    () => () => {
      alive.current = false;
    },
    []
  );

  const reset = useCallback(() => {
    alive.current = false;
    forget(slot);
    setState({ phase: "idle" });
    setMeta({});
  }, [slot]);

  return { state, run, reset, meta };
}

/** One line of progress for a run in flight. */
export function RunProgress({ state }: { state: RunState }) {
  if (state.phase === "starting")
    return <span className="font-mono text-xs text-muted">queuing…</span>;
  if (state.phase === "running") {
    const s = state.status;
    return (
      <span className="font-mono text-xs text-accent tnum">
        {s.status === "queued"
          ? `queued${s.queue_position ? ` · #${s.queue_position} in line` : ""}`
          : `running · ${s.completed_tests}/${s.total_tests}`}
      </span>
    );
  }
  return null;
}
