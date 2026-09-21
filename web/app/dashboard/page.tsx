"use client";

import { useEffect, useState } from "react";
import { RequireAuth, useAuth } from "@/components/AuthProvider";
import GrafanaDashboard, { GRAFANA_URL, HAS_GRAFANA, SLUG, UID } from "@/components/GrafanaPanel";
import MyRuns from "@/components/MyRuns";
import { Rule } from "@/components/ui";

/* Two dashboards, for two questions.

   "What have my runs done?" — §1, drawn by the app from the API, for
   the person signed in. Grafana cannot answer it: its metrics carry a
   model and a suite, never a user, so it can only show the instance.

   "Is the machine healthy?" — §2, the provisioned Grafana dashboard,
   embedded panel by panel rather than reimplemented, the same panels
   the alert rules fire on. It is the instance's picture, so it is the
   admin's, and it exists only where Grafana does (the compose stack;
   the hosted deployment runs one API container and no Prometheus).

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

function Dashboard() {
  const { user } = useAuth();
  const admin = user?.role === "admin";

  return (
    /* Break out of the page column — instruments need the width. */
    <div className="-mx-5 px-5 lg:-mx-[calc((100vw-72rem)/2)] lg:px-[calc((100vw-72rem)/2)]">
      <header className="space-y-1">
        <p className="label-xs">§ Dashboard</p>
        <h1 className="font-display text-3xl">
          {admin ? "Every run, and the machine under them" : "Your runs"}
        </h1>
        <p className="max-w-3xl text-sm text-muted">
          {admin
            ? "Every run on this instance, counted the way each run report counts it; then the operations view from Grafana, the same panels the alert rules fire on."
            : "Every run you have made, counted the way each run report counts it — pass rates, what it cost, and how your models compared. Nobody else's runs are here, and yours are on nobody else's page."}
        </p>
      </header>

      <div className="mt-8">
        <MyRuns admin={!!admin} />
      </div>

      {admin && HAS_GRAFANA && <Ops />}
    </div>
  );
}

function Ops() {
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

  return (
    <div className="mt-12">
      <Rule label="§2 · The machine — operations view" />
      <p className="mt-3 max-w-3xl text-sm text-muted">
        The provisioned Grafana dashboard, embedded rather than
        reimplemented — the same panels the alert rules fire on, so the
        page and the alerts cannot disagree. The whole instance, every
        user; the metrics carry a model and a suite, never a person.
      </p>

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
          href={`${GRAFANA_URL}/d/${UID}/${SLUG}?orgId=1&from=now-${range}&to=now`}
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

      <div className="mt-6">
        <GrafanaDashboard range={range} />
      </div>

      <p className="mt-10 pb-4 text-xs text-muted">
        Panels are rendered by Grafana from Prometheus. Nothing in this
        section is computed by the web app, so what you see here is what
        alerting sees.
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
