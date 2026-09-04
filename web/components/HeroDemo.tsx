"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import fixture from "@/lib/fixtures/hero-run.json";
import { explainAssertion } from "@/lib/explain";
import { Status } from "@/components/ui";

/* Stage timeline. Durations are the dwell time of each stage. */
const STAGES = [
  { key: "prompt", label: "01 · Prompt", ms: 1500 },
  { key: "dispatch", label: "02 · Model", ms: 1100 },
  { key: "response", label: "03 · Response", ms: 2200 },
  { key: "checks", label: "04 · Checks", ms: 3200 },
  { key: "aggregate", label: "05 · Score", ms: 1100 },
  { key: "result", label: "06 · Result", ms: 1800 },
  { key: "reveal", label: "07 · —", ms: 2600 },
] as const;

type Result = {
  model: string;
  avg_score: number;
  total_cost_usd: number;
  results: {
    prompt: string;
    actual: string;
    score: number | null;
    latency_ms: number;
    assertions: {
      type: string;
      passed: boolean;
      score: number;
      detail: string;
    }[];
  }[];
};

const run = fixture as unknown as Result;
const test = run.results[0];
const CHECKS = test.assertions;

export default function HeroDemo() {
  const [stage, setStage] = useState(0);
  const [typed, setTyped] = useState(0);
  const [resolved, setResolved] = useState(0);
  const [latency, setLatency] = useState(0);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced.current) {
      setStage(STAGES.length - 1);
      setTyped(test.actual.length);
      setResolved(CHECKS.length);
      setLatency(test.latency_ms);
    }
  }, []);

  const replay = useCallback(() => {
    setStage(0);
    setTyped(0);
    setResolved(0);
    setLatency(0);
  }, []);

  /* Stage clock */
  useEffect(() => {
    if (reduced.current) return;
    const t = setTimeout(
      () => setStage((s) => (s + 1) % STAGES.length),
      STAGES[stage].ms
    );
    return () => clearTimeout(t);
  }, [stage]);

  /* Reset derived state when the loop restarts */
  useEffect(() => {
    if (stage === 0 && !reduced.current) {
      setTyped(0);
      setResolved(0);
      setLatency(0);
    }
  }, [stage]);

  /* 02 — latency counter ticks up while the request is in flight */
  useEffect(() => {
    if (reduced.current || stage !== 1) return;
    const id = setInterval(
      () => setLatency((v) => Math.min(v + 37, test.latency_ms)),
      40
    );
    return () => clearInterval(id);
  }, [stage]);

  /* 03 — response streams in, counter freezes at the recorded value */
  useEffect(() => {
    if (reduced.current || stage !== 2) return;
    setLatency(test.latency_ms);
    const step = Math.max(1, Math.ceil(test.actual.length / 110));
    const id = setInterval(
      () => setTyped((n) => Math.min(n + step, test.actual.length)),
      18
    );
    return () => clearInterval(id);
  }, [stage]);

  /* 04 — checks resolve one at a time */
  useEffect(() => {
    if (reduced.current || stage !== 3) return;
    setTyped(test.actual.length);
    const id = setInterval(
      () => setResolved((n) => Math.min(n + 1, CHECKS.length)),
      STAGES[3].ms / (CHECKS.length + 1)
    );
    return () => clearInterval(id);
  }, [stage]);

  useEffect(() => {
    if (stage >= 4) setResolved(CHECKS.length);
  }, [stage]);

  const passedCount = useMemo(
    () => CHECKS.filter((c) => c.passed).length,
    []
  );

  const at = (s: number) => stage >= s;

  return (
    <section className="panel overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
        <div className="flex items-baseline gap-2">
          <span className="label-xs">Fig. 1</span>
          <span className="font-mono text-xs text-muted">
            {STAGES[stage].label}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="label-xs hidden sm:inline">
            a real evaluation, recorded
          </span>
          <button
            onClick={replay}
            className="btn btn-ghost px-2 py-0.5 font-mono text-[11px]"
          >
            replay
          </button>
        </div>
      </header>

      {/* stage progress track */}
      <div className="flex h-0.5 w-full">
        {STAGES.map((s, i) => (
          <div
            key={s.key}
            className={`h-full flex-1 ${
              i <= stage ? "bg-accent" : "bg-line"
            } transition-colors duration-200`}
          />
        ))}
      </div>

      <div className="grid gap-0 md:grid-cols-2">
        {/* ── Left: prompt → model → response ── */}
        <div className="space-y-4 border-line p-4 md:border-r">
          <div>
            <p className="label-xs mb-1.5">01 · Prompt</p>
            <p className="border-l-2 border-primary pl-3 text-sm leading-relaxed">
              {test.prompt.trim()}
            </p>
          </div>

          <div
            className={`transition-opacity duration-200 ${
              at(1) ? "opacity-100" : "opacity-0"
            }`}
          >
            <p className="label-xs mb-1.5">02 · Model</p>
            <div className="flex items-center justify-between gap-2 border border-line bg-surface-sunk px-3 py-2">
              <span className="font-mono text-xs">{run.model}</span>
              <span className="font-mono text-xs text-accent tnum">
                {latency > 0 ? `${Math.round(latency)} ms` : "…"}
              </span>
            </div>
          </div>

          <div
            className={`transition-opacity duration-200 ${
              at(2) ? "opacity-100" : "opacity-0"
            }`}
          >
            <p className="label-xs mb-1.5">03 · Response</p>
            <p className="min-h-[5.5rem] border-l-2 border-line pl-3 text-sm leading-relaxed text-muted">
              {test.actual.slice(0, typed)}
              {typed < test.actual.length && (
                <span className="text-accent">▌</span>
              )}
            </p>
          </div>
        </div>

        {/* ── Right: checks → score → result ── */}
        <div className="space-y-4 p-4">
          <div>
            <p className="label-xs mb-2">
              04 · Checks — one answer, {CHECKS.length} kinds of check
            </p>
            <ul className="space-y-1.5">
              {CHECKS.map((c, i) => {
                const done = i < resolved;
                return (
                  <li
                    key={c.type}
                    className={`flex items-baseline justify-between gap-3 text-sm ${
                      done ? "tick-in" : "opacity-35"
                    }`}
                  >
                    <span className="flex-1 leading-snug">
                      {done ? explainAssertion(c) : "—"}
                    </span>
                    <span className="shrink-0">
                      <Status state={done ? (c.passed ? "pass" : "fail") : "pending"}>
                        {c.type}
                      </Status>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div
            className={`transition-opacity duration-200 ${
              at(4) ? "opacity-100" : "opacity-0"
            }`}
          >
            <p className="label-xs mb-1.5">05 · Score</p>
            <p className="font-mono text-sm tnum">
              {passedCount}/{CHECKS.length} checks passed
              <span className="text-muted"> → weighted mean </span>
              <span className="text-accent">{test.score?.toFixed(3)}</span>
            </p>
          </div>

          <div
            className={`transition-opacity duration-200 ${
              at(5) ? "opacity-100" : "opacity-0"
            }`}
          >
            <p className="label-xs mb-2">06 · Result</p>
            <div className="grid grid-cols-3 gap-3">
              <Readout label="Score" value={test.score?.toFixed(3) ?? "—"} />
              <Readout
                label="Latency"
                value={`${(test.latency_ms / 1000).toFixed(2)}s`}
              />
              <Readout
                label="Cost"
                value={`$${run.total_cost_usd.toFixed(6)}`}
              />
            </div>
            <p className="mt-2 text-xs leading-snug text-muted">
              One test. Across a full suite EvalBench adds bootstrap
              confidence intervals, effect size, and regression detection
              against a baseline.
            </p>
          </div>
        </div>
      </div>

      <div
        className={`border-t border-line px-4 py-4 transition-opacity duration-300 ${
          at(6) ? "opacity-100" : "opacity-0"
        }`}
      >
        <p className="font-display text-xl">
          Five checks passed. One caught a claim the source never made.
          <span className="text-muted"> This is what EvalBench measures.</span>
        </p>
      </div>
    </section>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-t border-line-strong pt-1.5">
      <p className="label-xs">{label}</p>
      <p className="font-mono text-lg leading-tight tnum">{value}</p>
    </div>
  );
}
