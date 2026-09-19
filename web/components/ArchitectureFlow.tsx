"use client";

import { useEffect, useRef, useState } from "react";

/* ──────────────────────────────────────────────────────────────
   The system, drawn accurately and traced one hop at a time.

   Deliberately a depiction, not an execution: a homepage that
   fires real work on every visit can rate-limit, cost money and
   fail in front of the person you most wanted to impress. Every
   figure below is real — captured from actual runs — but nothing
   here calls the engine.
   ────────────────────────────────────────────────────────────── */

type NodeId =
  | "suite"
  | "api"
  | "queue"
  | "worker"
  | "providers"
  | "assert"
  | "stats"
  | "mongo"
  | "metrics"
  | "prom"
  | "grafana";

type Box = {
  id: NodeId;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub: string;
};

/* viewBox is 920×268. Two tall columns anchor the left and right
   edges; two dense rows run between them, with the observability
   band underneath. Kept deliberately tight — an airy diagram reads
   as decoration next to the specification below it. */
const BOXES: Box[] = [
  { id: "suite", x: 8, y: 14, w: 150, h: 146, label: "Suite", sub: "YAML" },
  { id: "api", x: 202, y: 14, w: 150, h: 56, label: "FastAPI", sub: "202 accepted" },
  { id: "queue", x: 396, y: 14, w: 150, h: 56, label: "Redis", sub: "job queue" },
  { id: "worker", x: 590, y: 14, w: 150, h: 56, label: "RQ worker", sub: "scale ×N" },
  { id: "providers", x: 784, y: 14, w: 128, h: 146, label: "Providers", sub: "" },

  { id: "assert", x: 590, y: 104, w: 150, h: 56, label: "Assertions", sub: "14 check types" },
  { id: "stats", x: 396, y: 104, w: 150, h: 56, label: "Statistics", sub: "t-test · McNemar · CI" },
  { id: "mongo", x: 202, y: 104, w: 150, h: 56, label: "MongoDB", sub: "suites + runs" },

  { id: "metrics", x: 202, y: 196, w: 150, h: 56, label: "/metrics", sub: "api + every worker" },
  { id: "prom", x: 396, y: 196, w: 150, h: 56, label: "Prometheus", sub: "29 metrics · 9 alerts" },
  { id: "grafana", x: 590, y: 196, w: 150, h: 56, label: "Grafana", sub: "dashboard" },
];

/* The three ways a suite reaches the API — drawn inside the Suite
   box so the left edge carries real information instead of air. */
const ENTRYPOINTS = ["evalbench run", "web workbench", "GitHub Action"];

/* Six providers, your own endpoint, or answers you already have — the
   last two are the paths that need no key at all. Eight lines at 14px
   fit the block; the list is the truth, so it is not cut to fit. */
const PROVIDERS = [
  "ollama", "groq", "gemini", "github", "openrouter", "openai",
  "your endpoint", "your answers",
];

type Stage = {
  /** Edge being traversed: [from, to]. */
  edge: [NodeId, NodeId];
  /** Path the packet travels, in viewBox coordinates. */
  d: string;
  caption: string;
};

const STAGES: Stage[] = [
  {
    edge: ["suite", "api"],
    d: "M158 42 H198",
    caption: "A suite is a list of prompts and the checks each answer must pass.",
  },
  {
    edge: ["api", "queue"],
    d: "M352 42 H392",
    caption:
      "The API returns immediately and queues the work — a long evaluation never holds a request open.",
  },
  {
    edge: ["queue", "worker"],
    d: "M546 42 H586",
    caption:
      "A worker picks the job up. Add more workers to run more evaluations at once.",
  },
  {
    edge: ["worker", "providers"],
    d: "M740 42 H780",
    caption:
      "The same suite runs against a local model, a hosted one, your own endpoint, or answers you already have — one interface.",
  },
  {
    edge: ["providers", "assert"],
    d: "M784 132 H744",
    caption:
      "Every answer is checked — string, format, meaning, groundedness, latency and cost. All must pass.",
  },
  {
    edge: ["assert", "stats"],
    d: "M590 132 H550",
    caption:
      "Each test is sampled repeatedly, so the score sits on a stable measurement rather than one coin flip.",
  },
  {
    edge: ["stats", "mongo"],
    d: "M396 132 H356",
    caption:
      "Suites and runs persist, scoped to whoever created them. Nobody sees anyone else's work.",
  },
  {
    edge: ["worker", "metrics"],
    d: "M665 70 V88 H180 V224 H198",
    caption:
      "Metrics come from the process that actually ran the evaluation, not just the API.",
  },
  {
    edge: ["metrics", "prom"],
    d: "M352 224 H392",
    caption:
      "Nine alert rules watch pass rate, cost, flakiness, safety and regressions.",
  },
  {
    edge: ["prom", "grafana"],
    d: "M546 224 H586",
    caption:
      "A provisioned dashboard, so the stack comes up already instrumented.",
  },
];

const STAGE_MS = 2600;

export default function ArchitectureFlow() {
  const [stage, setStage] = useState(0);
  const [running, setRunning] = useState(true);

  useEffect(() => {
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (reduce) {
      setRunning(false);
      return;
    }
    if (!running) return;
    const t = setInterval(
      () => setStage((s) => (s + 1) % STAGES.length),
      STAGE_MS
    );
    return () => clearInterval(t);
  }, [running]);

  // Restart the packet on every stage, after the new <animateMotion> is
  // in the DOM. Without this it never runs at all past the first hop.
  const motion = useRef<SVGAnimateMotionElement>(null);
  useEffect(() => {
    if (!running) return;
    motion.current?.beginElement?.();
  }, [stage, running]);

  const active = STAGES[stage];
  const lit = new Set<NodeId>(active.edge);

  return (
    <figure className="space-y-3">
      <div className="panel overflow-x-auto p-3 sm:p-5">
        <svg
          viewBox="0 0 920 268"
          className="w-full min-w-[640px]"
          role="img"
          aria-label="EvalBench architecture: a suite is submitted to the API, queued in Redis, executed by a worker against a model provider, checked by the assertion engine, aggregated with statistics, stored in MongoDB, and observed through Prometheus and Grafana."
        >
          {/* Arrowheads. A system diagram without them makes the
              reader guess which way the data goes. */}
          <defs>
            <marker
              id="af-head"
              viewBox="0 0 8 8"
              refX={7}
              refY={4}
              markerWidth={5}
              markerHeight={5}
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" className="fill-line-strong" />
            </marker>
            <marker
              id="af-head-on"
              viewBox="0 0 8 8"
              refX={7}
              refY={4}
              markerWidth={5}
              markerHeight={5}
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" className="fill-accent" />
            </marker>
          </defs>

          {/* every connector, always visible so the whole system reads
              at rest; only the active hop is emphasised */}
          <g className="stroke-line-strong" strokeWidth={1} fill="none">
            {STAGES.map((s) => (
              <path key={s.d} d={s.d} markerEnd="url(#af-head)" />
            ))}
          </g>

          {/* the active hop */}
          <path
            d={active.d}
            className="stroke-accent"
            strokeWidth={1.75}
            fill="none"
            markerEnd="url(#af-head-on)"
          />

          {/* The packet travelling it.

              `begin` has to be driven from script. A SMIL animation with
              no begin defaults to *document* time zero, so every stage
              after the first was created already past its own start and
              rendered frozen at the end of the path — the packet sat
              still on stage two onwards while stage one looked fine.
              beginElement() starts it relative to now. */}
          {running && (
            <rect
              width={7}
              height={7}
              className="fill-accent"
              transform="translate(-3.5,-3.5)"
            >
              <animateMotion
                ref={motion}
                key={stage}
                begin="indefinite"
                dur={`${STAGE_MS * 0.72}ms`}
                path={active.d}
                fill="freeze"
                calcMode="linear"
              />
            </rect>
          )}

          {BOXES.map((b) => {
            const on = lit.has(b.id);
            return (
              <g key={b.id}>
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  rx={2}
                  className={
                    on
                      ? "fill-accent-soft stroke-accent"
                      : "fill-surface stroke-line"
                  }
                  strokeWidth={1}
                />
                <text
                  x={b.x + 12}
                  y={b.y + 22}
                  className="fill-text font-mono text-[13px]"
                >
                  {b.label}
                </text>
                {b.sub && (
                  <text
                    x={b.x + 12}
                    y={b.y + 39}
                    className="fill-muted font-mono text-[10px]"
                  >
                    {b.sub}
                  </text>
                )}
                {b.id === "providers" &&
                  PROVIDERS.map((p, i) => (
                    <text
                      key={p}
                      x={b.x + 12}
                      y={b.y + 40 + i * 14}
                      className="fill-muted font-mono text-[10px]"
                    >
                      {p}
                    </text>
                  ))}
                {b.id === "suite" &&
                  ENTRYPOINTS.map((e, i) => (
                    <text
                      key={e}
                      x={b.x + 12}
                      y={b.y + 66 + i * 16}
                      className="fill-muted font-mono text-[10px]"
                    >
                      {e}
                    </text>
                  ))}
              </g>
            );
          })}
        </svg>
      </div>

      {/* Caption only. Each stage also carried a line of technical
          detail on the right, which competed with the sentence that
          actually explains the hop. */}
      <figcaption>
        <p className="max-w-3xl text-sm leading-relaxed">{active.caption}</p>
      </figcaption>

      {/* stage ticks — doubles as a progress read-out and manual control */}
      <div className="flex items-center gap-1.5">
        {STAGES.map((s, i) => (
          <button
            key={s.d}
            type="button"
            aria-label={`Step ${i + 1}: ${s.caption}`}
            aria-current={i === stage}
            onClick={() => {
              setStage(i);
              setRunning(false);
            }}
            className={`h-1.5 flex-1 transition-colors ${
              i === stage ? "bg-accent" : "bg-line hover:bg-line-strong"
            }`}
          />
        ))}
        <span className="ml-2 font-mono text-[10px] text-muted tnum">
          {String(stage + 1).padStart(2, "0")}/{STAGES.length}
        </span>
      </div>
    </figure>
  );
}
