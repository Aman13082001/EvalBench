"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import yaml from "js-yaml";
import { importSuite, listSuites, SuiteDoc } from "@/lib/api";
import { EXAMPLE_SUITE } from "@/lib/example";
import { RequireAuth } from "@/components/AuthProvider";
import { Panel, Rule, Status } from "@/components/ui";

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
          <p className="label-xs">§ Suites</p>
          <h1 className="font-display text-3xl">Your suites</h1>
          <p className="text-sm text-muted">
            Saved suites keep their run history and can hold a regression
            baseline.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "Cancel" : "New suite"}
        </button>
      </header>

      {error && (
        <div className="panel border-error p-3 text-sm text-error">{error}</div>
      )}

      {adding && (
        <Panel title="New suite" fig="+" caption="Paste or edit YAML, then save.">
          <form onSubmit={create} className="space-y-3">
            <textarea
              className="field h-72 resize-y font-mono text-xs leading-relaxed"
              spellCheck={false}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save suite"}
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
            No suites yet. Create one above, or try the{" "}
            <Link href="/run" className="text-accent hover:underline">
              playground
            </Link>{" "}
            first.
          </p>
        </Panel>
      )}

      <div className="space-y-3">
        {suites?.map((s) => (
          <Link key={s._id} href={`/suites/${s._id}`} className="block">
            <div className="panel p-4 transition-colors hover:border-primary">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-display text-lg">{s.name}</span>
                <span className="font-mono text-xs text-muted">
                  {s.provider ?? "ollama"} / {s.model}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
                <span>{s.tests?.length ?? 0} tests</span>
                <span>·</span>
                <span>{s.evaluator}</span>
                {s.baseline_run_id && (
                  <>
                    <span>·</span>
                    <Status state="pass">baseline set</Status>
                  </>
                )}
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
