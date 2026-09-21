"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getRunStatus,
  getRunSummary,
  getSuite,
  listRecentRuns,
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
   database — is forgotten quietly rather than shown as an error.

   With `latest`, the server is asked first: the person's newest run,
   wherever it was started — this tab, the benchmark page, the CLI —
   is what the form opens on, live if it is still going. The tab's
   memory only decides when the server cannot say. A run started from
   the benchmark page used to lose to an older one this tab remembered. */

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

export function useRun(slot?: string, opts: { latest?: boolean } = {}) {
  const [state, setState] = useState<RunState>({ phase: "idle" });
  const [meta, setMeta] = useState<RunMeta>({});
  /* Whether the run being shown was picked up rather than started by
     this form: the page then says what it is, and the form stays free
     to start another. */
  const [resumed, setResumed] = useState(false);
  const alive = useRef(true);
  /* Only the newest poll may speak. A resumed poll still in flight when
     the person starts a fresh run would otherwise keep writing the old
     run's progress over the new one's. */
  const gen = useRef(0);

  /* Poll until terminal. `resumed` runs forget a run the API refuses
     instead of reporting it: the form has nothing to say about a run it
     did not start in this life. */
  const poll = useCallback(
    async (runId: string, resumed = false): Promise<RunSummary | null> => {
      const mine = ++gen.current;
      const current = () => alive.current && gen.current === mine;
      while (current()) {
        let s: RunStatus;
        try {
          s = await getRunStatus(runId);
        } catch (e) {
          if (!current()) return null;
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
        if (!current()) return null;
        if (s.status === "completed") {
          try {
            const summary = await getRunSummary(runId);
            if (!current()) return null;
            setState({ phase: "done", runId, summary });
            return summary;
          } catch (e) {
            if (!current()) return null;
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
      setResumed(false);
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

  /* Pick up the newest run — the server's, or failing that this tab's. */
  useEffect(() => {
    if (!slot) return;
    let cancelled = false;
    const resume = (runId: string, m: RunMeta) => {
      alive.current = true;
      setMeta(m);
      setResumed(true);
      setState({
        phase: "running",
        runId,
        status: { run_id: runId, status: "queued", progress: 0, completed_tests: 0, total_tests: 0, error: null },
      });
      poll(runId, true);
    };
    const fromTab = () => {
      const saved = recall(slot);
      if (saved) resume(saved.runId, saved.meta || {});
    };
    if (!opts.latest) {
      fromTab();
      return;
    }
    (async () => {
      try {
        const [newest] = await listRecentRuns(1);
        if (cancelled) return;
        // An old failure is not something to open on; the tab may still
        // hold something worth resuming.
        if (!newest || newest.status === "failed") return fromTab();
        let suiteName: string | undefined;
        try {
          suiteName = (await getSuite(newest.suite_id)).name;
        } catch {
          /* the run still shows; the header falls back to the model */
        }
        if (cancelled) return;
        remember(slot, newest._id, { suiteName, model: newest.model, provider: newest.provider });
        resume(newest._id, { suiteName, model: newest.model, provider: newest.provider });
      } catch {
        if (!cancelled) fromTab();
      }
    })();
    return () => {
      cancelled = true;
    };
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
    gen.current += 1; // any poll in flight goes quiet
    forget(slot);
    setState({ phase: "idle" });
    setMeta({});
    setResumed(false);
  }, [slot]);

  return { state, run, reset, meta, resumed };
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
