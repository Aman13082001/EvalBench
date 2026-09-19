"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import yaml from "js-yaml";
import { importSuite, listSuites, SuiteDoc } from "@/lib/api";
import { EXAMPLE_SUITE } from "@/lib/example";
import { RequireAuth } from "@/components/AuthProvider";
import { Panel, Rule } from "@/components/ui";
import { JudgeFloorLine, ResolutionLine } from "@/components/BenchmarkLines";

function Suites() {
  const [suites, setSuites] = useState<SuiteDoc[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState(EXAMPLE_SUITE);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listSuites()
      .then(setSuites)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(load, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    let parsed: unknown;
    try {
      parsed = yaml.load(text);
    } catch (e) {
      setError(`YAML parse error: ${e}`);
      return;
    }
    setBusy(true);
    try {
      await importSuite(parsed);
      setAdding(false);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <p className="label-xs">§ Benchmarks</p>
          <h1 className="font-display text-3xl">Your benchmarks</h1>
          <p className="text-sm text-muted">
            Each one states what it measures and what it can resolve —
            the smallest drop it could actually detect. Open one to run it
            or read every test.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "Cancel" : "Import YAML"}
        </button>
      </header>

      {error && (
        <div className="panel border-error p-3 text-sm text-error">{error}</div>
      )}

      {adding && (
        <Panel
          title="Import a benchmark"
          fig="+"
          caption="Paste YAML and save. Re-importing a name you already have updates that benchmark in place. No YAML? Build one in the Workbench."
        >
          <form onSubmit={create} className="space-y-3">
            <textarea
              className="field h-72 resize-y font-mono text-xs leading-relaxed"
              spellCheck={false}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save benchmark"}
            </button>
          </form>
        </Panel>
      )}

      <Rule />

      {!suites && !error && (
        <p className="font-mono text-sm text-muted">loading…</p>
      )}

      {suites && suites.length === 0 && (
        <Panel>
          <p className="text-sm text-muted">
            No benchmarks yet. Paste YAML above, or build one in the{" "}
            <Link href="/workbench" className="text-accent hover:underline">
              Workbench
            </Link>
            .
          </p>
        </Panel>
      )}

      <div className="space-y-3">
        {suites?.map((s) => (
          <Link key={s._id} href={`/suites/${s._id}`} className="block">
            {/* A row answers "what does this measure" and nothing else.
                Model, check type and run history belong to the run and
                the detail page; here they were noise. */}
            <div className="panel p-4 transition-colors hover:border-primary">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-display text-lg">{s.name}</span>
                <span className="font-mono text-xs text-muted tnum">
                  {s.test_count ?? s.tests?.length ?? 0} tests
                </span>
              </div>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
                {s.description || (
                  <span className="italic">
                    No description yet — open it and add one line on what it measures.
                  </span>
                )}
              </p>
              <div className="mt-2 space-y-0.5">
                <ResolutionLine r={s.resolution} />
                <JudgeFloorLine f={s.judge_floor} />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Suites />
    </RequireAuth>
  );
}
