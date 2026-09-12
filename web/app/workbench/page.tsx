"use client";

import { useState } from "react";
import { RequireAuth } from "@/components/AuthProvider";
import BuildBenchmark from "@/components/workbench/BuildBenchmark";
import CompareModels from "@/components/workbench/CompareModels";
import RunEvaluation from "@/components/workbench/RunEvaluation";
import { useBenchmarks, useQuota } from "@/components/workbench/pickers";
import { Rule } from "@/components/ui";

/* The first page after signing in. Not a dashboard — the instrument.

   Hierarchy is deliberate: run an evaluation is the page; building a
   benchmark and comparing two models are the two things you do around
   it. Everything talks to the endpoints that already ran the CLI. */

function Workbench() {
  const benchmarks = useBenchmarks();
  // One quota for the page: a run in §1 must change the number shown in §4.
  const quota = useQuota();
  const [flash, setFlash] = useState<string | null>(null);

  return (
    <div className="space-y-10">
      <header className="space-y-1">
        <p className="label-xs">§1 · Run an evaluation</p>
        <h1 className="font-display text-3xl">Workbench</h1>
        <p className="max-w-2xl text-sm text-muted">
          Select a benchmark, select a model, run it. The result reads as a
          sentence first, then the numbers behind it, then every test.
        </p>
      </header>

      <RunEvaluation benchmarks={benchmarks} quota={quota} />

      <Rule label="§3 · Your own tests" />
      {flash && (
        <p className="font-mono text-xs text-success">{flash}</p>
      )}
      <BuildBenchmark
        defaultModel={{ provider: "groq", model: "openai/gpt-oss-20b" }}
        onCreated={(_, name) => {
          benchmarks.reload();
          setFlash(`“${name}” is now in your benchmarks — pick it above to run it.`);
        }}
      />

      <Rule label="§4 · Compare" />
      <CompareModels benchmarks={benchmarks} quota={quota} />
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Workbench />
    </RequireAuth>
  );
}
