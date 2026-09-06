"use client";

import { RequireAuth } from "@/components/AuthProvider";
import { Panel, Rule } from "@/components/ui";

const GRAFANA_URL =
  process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3000";
const DASHBOARD = "/d/evalbench-production/evalbench-e28094-production-overview";

/** Panels worth surfacing individually, by panel id in the provisioned
 *  dashboard (grafana/dashboards/evalbench.json). */
const PANELS: { id: number; title: string; note: string }[] = [
  { id: 40, title: "Est. cost — last run", note: "USD at list price." },
  { id: 41, title: "Cumulative cost", note: "Spend since the API started." },
  { id: 42, title: "Cost per run", note: "Trend by model and suite." },
  { id: 44, title: "Run outcomes", note: "Completed vs failed over time." },
  { id: 45, title: "Assertion scores", note: "Mean score by assertion type." },
];

function Dashboard() {
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="label-xs">§ Dashboard</p>
        <h1 className="font-display text-3xl">Operational metrics</h1>
        <p className="max-w-2xl text-sm text-muted">
          Live Prometheus data, rendered by the provisioned Grafana instance.
          Embedded rather than reimplemented — the same panels the alert rules
          fire on, so there is one source of truth.
        </p>
      </header>

      <Panel fig="!" title="Requires Grafana">
        <p className="text-sm leading-relaxed text-muted">
          These panels load from{" "}
          <span className="font-mono text-xs">{GRAFANA_URL}</span>. They render
          only if Grafana is running and allows embedding — set{" "}
          <span className="font-mono text-xs">
            GF_SECURITY_ALLOW_EMBEDDING=true
          </span>{" "}
          and, for anonymous viewing,{" "}
          <span className="font-mono text-xs">GF_AUTH_ANONYMOUS_ENABLED=true</span>{" "}
          on the Grafana service. Otherwise open it directly:{" "}
          <a
            href={`${GRAFANA_URL}${DASHBOARD}`}
            className="text-accent hover:underline"
            target="_blank"
            rel="noreferrer"
          >
            full dashboard →
          </a>
        </p>
      </Panel>

      <Rule label="Cost and throughput" />
      <div className="grid gap-4 md:grid-cols-2">
        {PANELS.map((p) => (
          <Panel key={p.id} title={p.title} fig={`P${p.id}`} caption={p.note}>
            <iframe
              src={`${GRAFANA_URL}${DASHBOARD}?orgId=1&panelId=${p.id}&kiosk&theme=light`}
              className="h-56 w-full border border-line bg-surface-sunk"
              loading="lazy"
              title={p.title}
            />
          </Panel>
        ))}
      </div>
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
