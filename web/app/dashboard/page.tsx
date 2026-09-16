"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/AuthProvider";
import GrafanaPanel, { GRAFANA_URL } from "@/components/GrafanaPanel";
import Reveal from "@/components/Reveal";
import { Rule } from "@/components/ui";

/* The operations view.

   Everything here is the provisioned Grafana dashboard, embedded panel
   by panel rather than reimplemented — the same panels the alert rules
   fire on, so there is one source of truth about what the system did.

   Laid out full-bleed because these are instruments: a 224px-tall
   timeseries squeezed into a text column is unreadable, and there is a
   whole screen available. */

const RANGES = [
  { id: "1h", label: "1h" },
  { id: "6h", label: "6h" },
  { id: "24h", label: "24h" },
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
] as const;

type Panel = {
  id: number;
  title: string;
  note?: string;
  height?: number;
  wide?: boolean;
};

const SECTIONS: {
  label: string;
  blurb: string;
  cols?: string;
  panels: Panel[];
}[] = [
  {
    label: "Now",
    cols: "sm:grid-cols-2 xl:grid-cols-4",
    blurb:
      "The state of the last run, live from the same gauges the alert rules read.",
    panels: [
      { id: 1, title: "Pass rate", note: "Most recent value per suite, over scored tests.", height: 190 },
      { id: 3, title: "Total runs", note: "Since the API started.", height: 190 },
      { id: 20, title: "Avg latency", note: "Mean time to an answer.", height: 190 },
      { id: 40, title: "Est. cost — last run", note: "USD at list price.", height: 190 },
    ],
  },
  {
    label: "Where the tests landed",
    blurb:
      "Every test this instance has run, by capability and outcome. "
      + "Infrastructure errors are counted apart from model failures — "
      + "a provider timing out is not the model getting an answer wrong.",
    panels: [
      { id: 32, title: "Tests by category and status", note: "Passed, failed and errored per capability.", height: 300, wide: true },
      { id: 33, title: "Infra errors — last run", note: "Requests that never produced an answer.", height: 220 },
      { id: 19, title: "Error rate by model", note: "Infrastructure failures over time, not model failures.", height: 220 },
    ],
  },
  {
    label: "Performance and latency",
    blurb:
      "Averages hide the tail. The percentile split and the heatmap are where a slow model actually shows up.",
    panels: [
      { id: 5, title: "Latency percentiles", note: "p50 / p95 / p99.", height: 340 },
      { id: 10, title: "Latency heatmap by model", note: "Distribution, not a mean.", height: 340 },
      { id: 6, title: "Test execution rate", note: "Passed vs failed vs error.", height: 320 },
      { id: 11, title: "Suite duration p95", note: "How long a whole run takes.", height: 320 },
    ],
  },
  {
    label: "Quality and regression",
    blurb:
      "The trends a deploy gate reads: score over time, capability by category, and how much of the movement is noise.",
    panels: [
      { id: 14, title: "Average score trend", note: "Mean score across runs.", height: 320 },
      { id: 31, title: "Category pass rate trend", note: "Where a model gained or lost.", height: 320 },
      { id: 30, title: "Category pass rate — latest", note: "Per capability, last run.", height: 320 },
      { id: 34, title: "Sample variance / flakiness", note: "Spread between samples of the same test.", height: 320 },
      { id: 16, title: "Regression p-value", note: "Below 0.05 is a real difference, not noise. Populates once a run is compared to a baseline.", height: 300 },
      { id: 17, title: "Regression mean difference", note: "Size of the move, in score points. Populates once a run is compared to a baseline.", height: 300 },
    ],
  },
  {
    label: "Cost and tokens",
    blurb:
      "Evaluation is not free. This is what the measurement itself spent.",
    panels: [
      { id: 41, title: "Cumulative cost", note: "All runs, since the API started.", height: 300 },
      { id: 42, title: "Cost per run", note: "Trend by model and suite.", height: 300 },
      { id: 43, title: "Token throughput", note: "Tokens per second.", height: 300 },
      { id: 44, title: "Run outcomes", note: "Completed vs failed over time.", height: 300 },
    ],
  },
  {
    label: "Assertion quality",
    blurb:
      "How each kind of check scores — the RAG assertions especially, which are the strictest ones EvalBench ships.",
    panels: [
      { id: 45, title: "Mean assertion score by type", note: "Including faithfulness and context recall.", height: 320 },
      { id: 18, title: "Score distribution", note: "Where scores actually fall, not just their mean.", height: 320 },
    ],
  },
  {
    label: "Instrumentation",
    blurb:
      "The scrape itself: what the API and the worker are reporting.",
    panels: [
      { id: 109, title: "Provider request rate", note: "By provider and status, including rate limits.", height: 300 },
      { id: 112, title: "Samples per test", note: "Requested versus actually scored.", height: 300 },
    ],
  },
];

function Dashboard() {
  // 7d by default: evaluation runs are occasional, and an hour of
  // an idle instance is an empty chart that reads as broken.
  const [range, setRange] = useState<string>("7d");
  const [reachable, setReachable] = useState<boolean | null>(null);

  /* Grafana is a separate service and is often simply not running. An
     iframe cannot report a cross-origin failure, so probe it once: an
     opaque response still proves something answered. */
  useEffect(() => {
    let alive = true;
    fetch(`${GRAFANA_URL}/api/health`, { mode: "no-cors" })
      .then(() => alive && setReachable(true))
      .catch(() => alive && setReachable(false));
    return () => {
      alive = false;
    };
  }, []);

  const total = SECTIONS.reduce((n, s) => n + s.panels.length, 0);

  return (
    /* Break out of the page column — instruments need the width. */
    <div className="-mx-5 px-5 lg:-mx-[calc((100vw-72rem)/2)] lg:px-[calc((100vw-72rem)/2)]">
      <header className="space-y-1">
        <p className="label-xs">§ Dashboard</p>
        <h1 className="font-display text-3xl">Operational metrics</h1>
        <p className="max-w-3xl text-sm text-muted">
          {total} panels from the provisioned Grafana instance, embedded
          rather than reimplemented — the same ones the alert rules fire on,
          so the page and the alerts cannot disagree. Panels load as you
          reach them.
        </p>
      </header>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          <span className="label-xs mr-1">range</span>
          {RANGES.map((r) => (
            <button
              key={r.id}
              onClick={() => setRange(r.id)}
              className={`btn px-2 py-1 font-mono text-[11px] ${
                range === r.id ? "btn-primary" : "btn-ghost"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <a
          href={`${GRAFANA_URL}/d/evalbench-production/evalbench-e28094-production-overview?orgId=1&from=now-${range}&to=now`}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-xs text-accent hover:underline"
        >
          open the full dashboard ↗
        </a>
      </div>

      {reachable === false && (
        <div className="panel mt-4 border-warning/60 p-3 text-sm">
          <p>
            <span className="font-medium text-warning">
              Grafana is not answering at {GRAFANA_URL}.
            </span>{" "}
            The panels below will stay empty until it is up.
          </p>
          <p className="mt-1 text-xs text-muted">
            Start it with <span className="font-mono">docker compose up -d
            grafana</span>. Embedding also needs{" "}
            <span className="font-mono">GF_SECURITY_ALLOW_EMBEDDING=true</span>{" "}
            and, for anonymous viewing,{" "}
            <span className="font-mono">GF_AUTH_ANONYMOUS_ENABLED=true</span> —
            both already set in this repo&rsquo;s compose file.
          </p>
        </div>
      )}

      {SECTIONS.map((section) => (
        <section key={section.label} className="mt-10 space-y-4">
          <Rule label={section.label} />
          <Reveal>
            {() => (
              <p className="max-w-3xl text-sm leading-relaxed text-muted">
                {section.blurb}
              </p>
            )}
          </Reveal>

          <div className={`grid gap-4 ${section.cols ?? "lg:grid-cols-2"}`}>
            {section.panels.map((p, i) => (
              <div key={p.id} className={p.wide ? "lg:col-span-2" : ""}>
                <GrafanaPanel
                  id={p.id}
                  title={p.title}
                  note={p.note}
                  height={p.height}
                  range={range}
                  delay={Math.min(i, 3) * 60}
                />
              </div>
            ))}
          </div>
        </section>
      ))}

      <p className="mt-10 pb-4 text-xs text-muted">
        Panels are rendered by Grafana from Prometheus. Nothing on this page
        is computed by the web app, so what you see here is what alerting
        sees.
      </p>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
