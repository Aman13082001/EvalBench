"use client";

import { useCallback, useRef, useState } from "react";
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
   the two cannot drift. */

export type RunState =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "running"; runId: string; status: RunStatus }
  | { phase: "done"; runId: string; summary: RunSummary }
  | { phase: "failed"; runId?: string; error: string };

const POLL_MS = 1500;

export function useRun() {
  const [state, setState] = useState<RunState>({ phase: "idle" });
  const alive = useRef(true);

  const run = useCallback(
    async (suiteId: string, opts: RunOptions): Promise<RunSummary | null> => {
      alive.current = true;
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

      // poll the existing status endpoint until terminal
      while (alive.current) {
        let s: RunStatus;
        try {
          s = await getRunStatus(runId);
        } catch (e) {
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
    []
  );

  const reset = useCallback(() => {
    alive.current = false;
    setState({ phase: "idle" });
  }, []);

  return { state, run, reset };
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
