"use client";

import { useEffect, useState } from "react";
import { getPlaygroundInfo, PlaygroundInfo } from "@/lib/api";

export default function Home() {
  const [info, setInfo] = useState<PlaygroundInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getPlaygroundInfo().then(setInfo).catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="space-y-6">
      <section className="card p-6">
        <h1 className="text-2xl font-bold">Try an LLM evaluation in your browser</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-300">
          Write a suite of prompts and assertions, run it against a hosted model
          with your own free API key, and get a scored report — pass rate with a
          bootstrap CI, per-assertion breakdown, cost, and category rollup.
          Nothing is stored except a 24-hour permalink.
        </p>
        <a href="/run" className="btn mt-4 inline-block">
          Open the editor
        </a>
      </section>

      <section className="card p-4 text-sm">
        {err && <p className="text-bad">API unreachable: {err}</p>}
        {!err && !info && <p className="text-slate-400">Connecting to API…</p>}
        {info && (
          <p className="text-slate-300">
            Connected. Providers:{" "}
            <span className="text-accent">{info.providers.join(", ")}</span> ·
            up to {info.max_tests} tests · {info.max_samples} samples.
          </p>
        )}
      </section>
    </div>
  );
}
