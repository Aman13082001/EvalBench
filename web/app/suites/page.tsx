"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import yaml from "js-yaml";
import { importSuite, JudgeFloor, listSuites, Resolution, SuiteDoc } from "@/lib/api";
import { EXAMPLE_SUITE } from "@/lib/example";
import { RequireAuth } from "@/components/AuthProvider";
import { Panel, Rule } from "@/components/ui";

/* The line that makes this a list of instruments rather than a list of
   files. A benchmark's precision is not a property of its YAML — it is
   the spread between runs of it, so a benchmark nobody has run twice
   reports nothing and says why. See research/REPORT.md: at ten tests a
   real regression is caught about 21% of the time. */
function ResolutionLine({ r }: { r?: Resolution }) {
  if (!r) return null;
  if (r.mde === null) {
    return (
      <p className="mt-2 font-mono text-[11px] text-muted">
        resolution: <span className="italic">{r.reason}</span>
      </p>
    );
  }
  const points = Math.round(r.mde * 100);
  return (
    <p className="mt-2 font-mono text-[11px] text-muted tnum">
      resolution: detects a drop of{" "}
      <span className="text-text">{points} points</span> or more · 80% power ·
      from {r.runs_used} runs
    </p>
  );
}

/* The judge's own contribution, under the resolution. A benchmark that
   asks a model to grade carries the grader's spread whatever its history
   says: research/judge-variance/ measured it, and this is that number
   scaled to this benchmark's size. A drop inside it is not evidence. */
function JudgeFloorLine({ f }: { f?: JudgeFloor | null }) {
  if (!f) return null;
  const pts = (x: number) => {
    const p = x * 100;
    return p < 1 ? "under 1 point" : `about ${p.toFixed(p < 3 ? 1 : 0)} points`;
  };
  return (
    <p className="font-mono text-[11px] text-muted tnum">
      judge floor: the grader alone moves the mean{" "}
      <span className="text-text">±{pts(f.rerun)}</span> between runs,{" "}
      <span className="text-text">±{pts(f.switch)}</span> across a judge change ·{" "}
      {f.judged === f.tests ? "every test judged" : `${f.judged} of ${f.tests} tests judged`} ·{" "}
      <Link href="/research#judge" className="underline decoration-line underline-offset-2 hover:text-text" onClick={(e) => e.stopPropagation()}>
        the study
      </Link>
    </p>
  );
}

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
              <ResolutionLine r={s.resolution} />
              <JudgeFloorLine f={s.judge_floor} />
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
