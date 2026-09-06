"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getRun, getRunSummary, RunSummary } from "@/lib/api";
import { RequireAuth } from "@/components/AuthProvider";
import Results from "@/components/Results";

function RunReport({ id }: { id: string }) {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getRunSummary(id), getRun(id)])
      .then(([summary, doc]) =>
        setRun({ ...summary, results: doc.results ?? [] })
      )
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  if (error) {
    return (
      <div className="panel border-error p-4 text-sm text-error">{error}</div>
    );
  }
  if (!run) return <p className="font-mono text-sm text-muted">loading…</p>;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="label-xs">
          <Link href="/suites" className="hover:text-text">
            § Suites
          </Link>{" "}
          / run
        </p>
        <h1 className="font-display text-3xl">Run report</h1>
        <p className="font-mono text-xs text-muted">
          {id} · {run.model}
        </p>
      </header>

      <Results r={run} />
    </div>
  );
}

export default function Page() {
  const params = useParams<{ id: string }>();
  return (
    <RequireAuth>
      <RunReport id={params.id} />
    </RequireAuth>
  );
}
