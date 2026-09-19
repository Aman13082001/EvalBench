"use client";

import { useState } from "react";
import ArchitectureFlow from "@/components/ArchitectureFlow";
import LoginDialog from "@/components/LoginDialog";
import { Rule } from "@/components/ui";
import judgeStudy from "@/lib/fixtures/judge-study.json";

/* ── §3c · Three findings ───────────────────────────────────────
   The thesis is that LLM evaluation is itself badly measured. These
   are the three numbers that say so, each from a study in this repo,
   each read live from the study's own output so the page cannot
   drift from the report. */
/* eslint-disable @typescript-eslint/no-explicit-any */
const J = judgeStudy as any;
const FINDINGS: { n: string; value: string; claim: string; detail: string; href: string }[] = [
  {
    n: "01",
    value: "21%",
    claim: "A ten-test suite catches a real regression one time in five.",
    detail:
      "Real paired outputs from two models, resampled 2,000 times at each suite size, with EvalBench's own detector run on every draw. Power does not reach 80% until somewhere past forty tests — and the failure is silent, toward false confidence.",
    href: "/research#power",
  },
  {
    n: "02",
    value: `${Math.round(J.gate.both_vs_mde * 100)}%`,
    claim: "Of a 5-point deploy gate, a third is the judge.",
    detail: `Sixty answers frozen, three judge models, five repeats each: a judge switch moves a ${J.n_tests}-test mean by ±${(J.floor.switch_judge_sd * 100).toFixed(1)} points and a re-run by ±${(J.floor.rerun_same_judge_sd * 100).toFixed(1)} before the model changes at all. Every judged benchmark here now shows its share of that floor.`,
    href: "/research#judge",
  },
  {
    n: "03",
    value: "2",
    claim: "Parser bugs found by being able to score frozen answers.",
    detail: `A rubric score of 1 — the worst verdict — was read as a perfect 1.0. Then ${J.no_verdict.total} of ${J.calls} judge replies came back empty, all on refusal prompts, and an empty reply was read as 3 of 5: the pass cutoff. Neither is visible unless you can feed a judge a deliberately wrong answer twice.`,
    href: "/research#judge",
  },
];

/* ── §3 · What it can do ────────────────────────────────────────
   Written as a specification rather than a feature grid: what it
   checks, how it decides something changed, where it runs, how it
   runs in production. Every figure is real. */

const CHECKS: { group: string; types: string; what: string }[] = [
  {
    group: "Exact & format",
    types: "exact · equals · contains · icontains · regex · json-schema",
    what: "Is the answer literally right, and is it shaped the way the caller needs?",
  },
  {
    group: "Meaning",
    types: "semantic · judge · llm-rubric",
    what: "Does it mean the same thing, even worded differently — graded by embedding distance or by a second model against a written rubric.",
  },
  {
    group: "Groundedness (RAG)",
    types: "faithfulness · context-recall · context-precision",
    what: "Did it stick to the retrieved source, did the source contain the answer, and was the retrieval relevant. Unsupported claims are named individually.",
  },
  {
    group: "Budgets",
    types: "latency · cost",
    what: "Was it fast enough and cheap enough to actually ship.",
  },
];

const CAPABILITIES: { title: string; body: string; detail: string }[] = [
  {
    title: "It decides whether a change is real",
    body: "A lower score is not a regression. Runs are compared against a promoted baseline with a paired t-test, an exact McNemar test on pass/fail outcomes, and a Cohen's d effect size — so a significant-but-tiny move is distinguishable from one that matters. Every headline number carries a bootstrap confidence interval.",
    detail:
      "paired t-test · exact McNemar · Cohen's d · 95% percentile bootstrap (2000 resamples)",
  },
  {
    title: "It tells you when your suite is too small to trust",
    body: "Alongside the verdict it reports the minimum number of tests needed to detect a five-point move at your measured variance. If your suite is under that, the tool says so instead of quietly reporting 'no regression detected'.",
    detail: "min_samples_for_5pt_mde, reported on every comparison",
  },
  {
    title: "It scores safety in both directions",
    body: "Refusing harm is half the job. A model that also declines 'how do I recognise a phishing email?' is broken in a way a refusal-only benchmark scores as perfect. Over-refusal is counted as a failure.",
    detail: "19 tests across 9 safety categories · refusal and over-refusal scored separately",
  },
  {
    title: "It runs the same suite on any model",
    body: "Local Ollama or five hosted providers behind one interface, with per-provider concurrency ceilings so free-tier rate limits are respected. Token counts and estimated cost come back normalised, so comparing two models is a config change.",
    detail: "ollama · groq · gemini · github · openrouter · openai",
  },
  {
    title: "It gates CI",
    body: "A composite GitHub Action spins up an ephemeral EvalBench, runs a suite against a pull request, fails the check on a low pass rate or a detected regression, and posts the result as a comment that updates in place.",
    detail: "evalbench run --fail-under 0.80 --compare-to-baseline",
  },
  {
    title: "It is instrumented like production software",
    body: "Runs execute as queued jobs on workers you can scale horizontally, with a startup reaper for anything a crash orphaned. Every run emits Prometheus metrics from the process that actually executed it, onto a provisioned Grafana dashboard.",
    detail: "29 metrics · 9 alert rules · async job queue · horizontal scaling",
  },
];

export default function Home() {
  const [loginOpen, setLoginOpen] = useState(false);

  return (
    <div className="space-y-12">
      {/* ── §1 · The system ─────────────────────────────────── */}
      <section className="space-y-5">
        <p className="label-xs">§1 · How it works</p>
        <h1 className="max-w-3xl font-display text-4xl leading-[1.15] sm:text-5xl">
          An instrument for measuring what a language model actually does.
        </h1>
        <ArchitectureFlow />
      </section>

      {/* ── §2 · Why ────────────────────────────────────────── */}
      <Rule label="§2 · Why I built it" />
      <section className="max-w-2xl space-y-3">
        <p className="text-base leading-relaxed">
          I kept getting eval results I couldn&rsquo;t trust. The same suite
          would score 84% one day and 89% the next against the same model, with
          no way to tell whether anything had actually changed.
        </p>
        <p className="text-base leading-relaxed">
          EvalBench answers that — it samples each test repeatedly and runs a
          paired statistical test before it will call a change real.
        </p>
        <p className="font-mono text-[11px] text-muted tnum">
          those two figures are real: 84.2% and 89.5% on the same safety suite
          and the same model, p = 0.429
        </p>
      </section>

      {/* ── §3a · What it checks ────────────────────────────── */}
      <Rule label="§3 · What it can do" />
      <section className="space-y-4">
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          A test passes only when every check on it passes. Fourteen check
          types, grouped by what they actually measure.
        </p>

        <div className="panel divide-y divide-line">
          {CHECKS.map((c) => (
            <div
              key={c.group}
              className="grid gap-1 p-4 sm:grid-cols-[11rem_1fr] sm:gap-5"
            >
              <div className="space-y-1">
                <p className="font-display text-base leading-none">{c.group}</p>
                <p className="font-mono text-[10px] leading-relaxed text-muted">
                  {c.types}
                </p>
              </div>
              <p className="text-sm leading-relaxed text-muted">{c.what}</p>
            </div>
          ))}
        </div>

        {/* ── §3b · Capabilities ────────────────────────────── */}
        <div className="grid gap-4 md:grid-cols-2">
          {CAPABILITIES.map((c) => (
            <section key={c.title} className="panel p-4">
              <h3 className="font-display text-base leading-snug">{c.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                {c.body}
              </p>
              <p className="mt-3 border-t border-line pt-2 font-mono text-[10px] leading-relaxed text-muted tnum">
                {c.detail}
              </p>
            </section>
          ))}
        </div>
      </section>

      {/* ── §3c · Three findings ────────────────────────────── */}
      <section className="space-y-4">
        <Rule label="§4 · Three findings" />
        <div className="max-w-2xl space-y-2">
          <p className="text-base leading-relaxed">
            The statistics above are not decoration. The instrument was built
            on the premise that <strong>LLM evaluation is itself badly
            measured</strong> — and then used to measure that.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {FINDINGS.map((f) => (
            <a
              key={f.n}
              href={f.href}
              className="panel group flex flex-col gap-3 p-4 transition-colors hover:border-primary"
            >
              <div className="flex items-baseline justify-between">
                <span className="label-xs font-mono">{f.n}</span>
                <span className="font-display text-4xl leading-none tnum">{f.value}</span>
              </div>
              <p className="font-display text-lg leading-snug">{f.claim}</p>
              <p className="text-sm leading-relaxed text-muted">{f.detail}</p>
              <span className="mt-auto font-mono text-[11px] text-muted group-hover:text-text">
                read the study →
              </span>
            </a>
          ))}
        </div>
        <p className="font-mono text-[11px] text-muted tnum">
          reproducible: python scripts/run_study_power.py · python scripts/run_study_judge.py
        </p>
      </section>

      {/* ── §5 · The door ───────────────────────────────────────
          The whole block is the control, not a small button beside a
          heading. "Sign in" is a chore; the invitation is to go and
          check, so the action says that. */}
      <Rule />
      <section className="pb-4">
        <button
          onClick={() => setLoginOpen(true)}
          className="group block w-full border border-line-strong bg-surface px-5 py-6 text-left
                     transition-colors duration-100 hover:border-accent hover:bg-accent-soft
                     focus:border-accent focus:outline-none sm:px-7 sm:py-7"
          style={{ borderRadius: 2 }}
        >
          <span className="flex flex-wrap items-stretch justify-between gap-5 sm:flex-nowrap">
            <span className="space-y-1.5">
              <span className="label-xs block text-accent">§5 · Go and check</span>
              <span className="block font-display text-3xl leading-none">
                Check it for yourself
              </span>
              <span className="block max-w-xl text-sm leading-relaxed text-muted">
                Run a real evaluation against your own model, your own
                endpoint, or answers you already have — and keep the history.
              </span>
            </span>

            {/* The actuator. Separated by a hairline and labelled, so the
                block reads as a control at rest rather than only on hover. */}
            <span
              className="flex shrink-0 items-center gap-3 self-center bg-accent-soft px-5 py-3"
              style={{ borderRadius: 2 }}
            >
              <span className="label-xs whitespace-nowrap text-accent">
                Sign in
              </span>
              <span
                aria-hidden
                className="font-mono text-xl leading-none text-accent transition-transform
                           duration-100 group-hover:translate-x-1"
              >
                →
              </span>
            </span>
          </span>
        </button>
      </section>

      <LoginDialog open={loginOpen} onClose={() => setLoginOpen(false)} />
    </div>
  );
}
