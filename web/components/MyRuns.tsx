"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DashboardData, getQuota, myDashboard, Quota } from "@/lib/api";
import { Metric, Panel, Rule } from "@/components/ui";

/* ── Your runs ─────────────────────────────────────────────────
   Drawn by the app, from the API, for the person signed in. Grafana
   cannot do this: its metrics carry no user, so it shows the instance.

   Forms, by the data's job. Four headline numbers are stat tiles, not
   charts. Runs per day is a magnitude over time: bars. Pass rate per
   day is a rate over time: a line, with a marker only on days that
   scored something and a gap where nothing did — a flat line through
   an empty day would claim a rate that was never measured. Two charts
   with one axis each, never one chart with two. Per model and per
   category are horizontal bars, so the label has room to be read.

   One series per chart, so one hue (the site's accent) and no legend.
   Numbers are in text ink; the mark beside them carries the meaning. */

const RANGES = [7, 30, 90] as const;

type Tip = { x: number; y: number; lines: string[] } | null;

function pct(x: number | null | undefined, digits = 0) {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}

function money(x: number) {
  return x === 0 ? "$0" : x < 0.001 ? `$${x.toFixed(6)}` : `$${x.toFixed(4)}`;
}

function shortDay(iso: string) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

/* A tooltip that follows the pointer, positioned inside the figure. */
function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded border border-line bg-bg px-2 py-1 font-mono text-[11px] leading-snug text-text shadow tnum"
      style={{ left: tip.x + 12, top: tip.y - 8, transform: "translateY(-100%)" }}
    >
      {tip.lines.map((l, i) => (
        <div key={i} className={i === 0 ? "text-muted" : ""}>{l}</div>
      ))}
    </div>
  );
}

/* Where the pointer is, in the figure's own pixels. */
function local(e: React.MouseEvent) {
  const r = (e.currentTarget as Element).closest("figure")!.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function RunsPerDay({ days }: { days: DashboardData["by_day"] }) {
  const [tip, setTip] = useState<Tip>(null);
  const W = 720, H = 150, L = 34, R = 8, T = 10, B = 26;
  const max = Math.max(1, ...days.map((d) => d.runs));
  const n = days.length;
  const step = (W - L - R) / n;
  const bw = Math.max(2, step - 2); // a 2px surface gap between bars
  const py = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = max <= 4 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  const labelEvery = n > 45 ? 14 : n > 10 ? 7 : 1;

  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Runs per day over the last ${n} days.`} onMouseLeave={() => setTip(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} y1={py(v)} x2={W - R} y2={py(v)} className="stroke-line" strokeWidth={1} />
            <text x={L - 8} y={py(v) + 4} textAnchor="end" className="fill-muted font-mono" fontSize={11}>{v}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const x = L + step * i + (step - bw) / 2;
          const y = py(d.runs);
          const h = H - B - y;
          return (
            <g key={d.day}>
              {/* the hit target is the whole column, bigger than the mark */}
              <rect
                x={L + step * i} y={T} width={step} height={H - T - B} fill="transparent"
                onMouseMove={(e) => setTip({ ...local(e), lines: [shortDay(d.day), `${d.runs} run${d.runs === 1 ? "" : "s"}`, d.scored ? `${d.passed}/${d.scored} tests passed` : "nothing scored"] })}
              />
              {d.runs > 0 && (
                <path
                  d={`M${x},${H - B} v${-(h - 4)} a4,4 0 0 1 4,-4 h${bw - 8} a4,4 0 0 1 4,4 v${h - 4} z`}
                  className="fill-accent"
                />
              )}
              {i % labelEvery === 0 && (
                <text x={L + step * (i + 0.5)} y={H - 8} textAnchor="middle" className="fill-muted font-mono" fontSize={10}>{shortDay(d.day)}</text>
              )}
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </figure>
  );
}

function PassRatePerDay({ days }: { days: DashboardData["by_day"] }) {
  const [tip, setTip] = useState<Tip>(null);
  const W = 720, H = 150, L = 40, R = 8, T = 10, B = 26;
  const n = days.length;
  const step = (W - L - R) / n;
  const px = (i: number) => L + step * (i + 0.5);
  const py = (v: number) => T + (H - T - B) * (1 - v);
  // one path per unbroken stretch of measured days
  const segments = useMemo(() => {
    const out: string[] = [];
    let cur: string[] = [];
    days.forEach((d, i) => {
      if (d.pass_rate == null) { if (cur.length) out.push(cur.join(" ")); cur = []; return; }
      cur.push(`${cur.length ? "L" : "M"}${px(i).toFixed(1)},${py(d.pass_rate).toFixed(1)}`);
    });
    if (cur.length) out.push(cur.join(" "));
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);
  const labelEvery = n > 45 ? 14 : n > 10 ? 7 : 1;

  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Pass rate per day over the last ${n} days; days with nothing scored are left blank.`} onMouseLeave={() => setTip(null)}>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={L} y1={py(v)} x2={W - R} y2={py(v)} className="stroke-line" strokeWidth={1} />
            <text x={L - 8} y={py(v) + 4} textAnchor="end" className="fill-muted font-mono" fontSize={11}>{pct(v)}</text>
          </g>
        ))}
        {segments.map((d, i) => (
          <path key={i} d={d} fill="none" className="stroke-accent" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {days.map((d, i) => (
          <g key={d.day}>
            <rect
              x={L + step * i} y={T} width={step} height={H - T - B} fill="transparent"
              onMouseMove={(e) => setTip({ ...local(e), lines: [shortDay(d.day), d.pass_rate == null ? "nothing scored" : `${pct(d.pass_rate, 1)} · ${d.passed}/${d.scored} passed`] })}
            />
            {d.pass_rate != null && (
              <circle cx={px(i)} cy={py(d.pass_rate)} r={4} className="fill-accent stroke-bg" strokeWidth={2} />
            )}
            {i % labelEvery === 0 && (
              <text x={px(i)} y={H - 8} textAnchor="middle" className="fill-muted font-mono" fontSize={10}>{shortDay(d.day)}</text>
            )}
          </g>
        ))}
      </svg>
      <Tooltip tip={tip} />
    </figure>
  );
}

/* Horizontal bars: one row per entity. The rate is the bar and the number
   beside it; everything else about the row sits under the bar in muted
   ink, so the bar keeps its width whatever the detail says. Read top to
   bottom by whatever the API sorted on. */
function Bars({ rows }: { rows: { key: string; label: string; sub?: string; rate: number | null; detail: string }[] }) {
  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.key} className="grid items-start gap-x-3 gap-y-1 sm:grid-cols-[minmax(9rem,13rem)_1fr]">
          <div className="min-w-0">
            <div className="truncate font-mono text-xs text-text">{r.label}</div>
            {r.sub && <div className="truncate font-mono text-[11px] text-muted">{r.sub}</div>}
          </div>
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-3">
              <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-line/60" role="img" aria-label={`${r.label}: ${pct(r.rate, 1)}`}>
                {r.rate != null && <div className="h-full rounded-sm bg-accent" style={{ width: `${Math.max(1, r.rate * 100)}%` }} />}
              </div>
              <span className="w-14 shrink-0 text-right font-mono text-xs text-text tnum">{pct(r.rate, 1)}</span>
            </div>
            <div className="font-mono text-[11px] text-muted tnum">{r.detail}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function MyRuns({ admin }: { admin: boolean }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [data, setData] = useState<DashboardData | null>(null);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setErr(null);
    Promise.all([myDashboard(days), getQuota()])
      .then(([d, q]) => { if (alive) { setData(d); setQuota(q); } })
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
  }, [days]);

  const t = data?.totals;
  const empty = data != null && t?.runs === 0;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Rule label={admin ? "§1 · Every run on this instance" : "§1 · Your runs"} />
        <div className="flex gap-1" role="tablist" aria-label="Window">
          {RANGES.map((r) => (
            <button key={r} role="tab" aria-selected={days === r} onClick={() => setDays(r)}
              className={`btn px-2 py-1 font-mono text-[11px] ${days === r ? "btn-primary" : "btn-ghost"}`}>
              {r}d
            </button>
          ))}
        </div>
      </div>

      {err && <p className="text-sm text-error">{err}</p>}

      <Panel>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Runs" value={t ? String(t.runs) : "…"} sub={t ? `${t.completed} completed · ${t.failed} failed` : undefined} />
          <Metric label="Pass rate" value={t ? pct(t.pass_rate, 1) : "…"} sub={t ? `${t.passed}/${t.scored} tests${t.errors ? ` · ${t.errors} errored` : ""}` : undefined} tone={t?.pass_rate == null ? "text" : t.pass_rate >= 0.8 ? "success" : t.pass_rate >= 0.5 ? "warning" : "error"} />
          <Metric label="Calls today" value={quota ? (quota.cap == null ? String(quota.used) : `${quota.used} / ${quota.cap}`) : "…"} sub={quota ? (quota.cap == null ? "on EvalBench's key · uncapped" : `${quota.remaining} left on EvalBench's key`) : undefined} />
          <Metric label="Spend" value={t ? money(t.cost_usd) : "…"} sub={t?.avg_latency_ms != null ? `avg ${Math.round(t.avg_latency_ms)} ms to an answer` : "at list price"} />
        </div>
      </Panel>

      {empty ? (
        <Panel>
          <p className="text-sm text-muted">
            Nothing in the last {days} days. Run a benchmark in the{" "}
            <Link href="/workbench" className="text-text underline decoration-line underline-offset-2 hover:text-accent">Workbench</Link>{" "}
            and it appears here — with the pass rate, what it cost, and how the models compared.
          </p>
        </Panel>
      ) : data && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Runs per day">
              <RunsPerDay days={data.by_day} />
            </Panel>
            <Panel title="Pass rate per day" caption="Blank where nothing was scored.">
              <PassRatePerDay days={data.by_day} />
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="By model" caption="Pass rate over every scored test, most-run first.">
              <Bars rows={data.by_model.map((m) => ({
                key: `${m.provider}/${m.model}`, label: m.model, sub: m.provider || undefined, rate: m.pass_rate,
                detail: `${m.runs} run${m.runs === 1 ? "" : "s"} · avg ${m.avg_score == null ? "—" : m.avg_score.toFixed(2)} · ${m.avg_latency_ms == null ? "—" : `${Math.round(m.avg_latency_ms)} ms`} · ${money(m.cost_usd)}`,
              }))} />
            </Panel>
            <Panel title="By category" caption="Where the models were strong or weak, across every run.">
              <Bars rows={data.by_category.map((c) => ({
                key: c.category, label: c.category, rate: c.pass_rate, detail: `${c.passed}/${c.scored}`,
              }))} />
            </Panel>
          </div>
        </>
      )}
    </section>
  );
}
