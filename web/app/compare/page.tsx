"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Comparison,
  compareRuns,
  endpointHost,
  getRunSummary,
  RunSummary,
} from "@/lib/api";
import { RequireAuth } from "@/components/AuthProvider";
import ComparisonReport from "@/components/ComparisonReport";
import { Rule } from "@/components/ui";

/* /compare?a=<run>&b=<run>

   Reconstructed from two existing runs every time it is opened — there
   is no comparison record to keep in sync, so it is shareable, and it
   stays correct if either run is ever re-summarised. */

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; a: RunSummary; b: RunSummary; c: Comparison };

function ComparePage() {
  const params = useSearchParams();
  const idA = params.get("a");
  const idB = params.get("b");
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    if (!idA || !idB) {
      setState({
        phase: "error",
        message: "Two run ids are needed: /compare?a=<run>&b=<run>",
      });
      return;
    }
    let alive = true;
    Promise.all([getRunSummary(idA), getRunSummary(idB), compareRuns(idA, idB)])
      .then(([a, b, c]) => alive && setState({ phase: "ready", a, b, c }))
      .catch(
        (e) =>
          alive &&
          setState({
            phase: "error",
            message: e instanceof Error ? e.message : String(e),
          })
      );
    return () => {
      alive = false;
    };
  }, [idA, idB]);

  if (state.phase === "loading")
    return <p className="font-mono text-sm text-muted">pairing the two runs…</p>;

  if (state.phase === "error")
    return (
      <div className="space-y-4">
        <div className="panel border-error p-4 text-sm text-error">{state.message}</div>
        <Link href="/workbench" className="btn btn-secondary">
          Back to the workbench
        </Link>
      </div>
    );

  const { a, b, c } = state;
  // A custom endpoint is part of the name; two runs of one model on two
  // servers are not "two runs of" the same thing.
  const nameOf = (r: { model: string; base_url?: string | null }) => {
    const host = endpointHost(r.base_url);
    return host ? `${r.model} at ${host}` : r.model;
  };
  const sameModel = nameOf(a) === nameOf(b);

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <p className="label-xs">
          <Link href="/workbench" className="hover:text-text">
            § Workbench
          </Link>{" "}
          / Compare
        </p>
        <h1 className="font-display text-3xl">
          {sameModel ? `Two runs of ${nameOf(a)}` : `${nameOf(a)} vs ${nameOf(b)}`}
        </h1>
        <p className="font-mono text-[11px] text-muted tnum">
          {c.test_count} paired tests · runs {idA?.slice(-8)} and {idB?.slice(-8)}
        </p>
      </header>

      <Rule label="Side by side" />
      <ComparisonReport baseline={a} candidate={b} comparison={c} mode="models" />

      <Rule />
      <p className="font-mono text-[11px] text-muted">
        share this comparison: {typeof window !== "undefined" ? window.location.href : ""}
      </p>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Suspense fallback={<p className="font-mono text-sm text-muted">loading…</p>}>
        <ComparePage />
      </Suspense>
    </RequireAuth>
  );
}
