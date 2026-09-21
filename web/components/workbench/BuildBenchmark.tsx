"use client";

import { useState } from "react";
import { importSuite } from "@/lib/api";
import { explainAssertion } from "@/lib/explain";
import { ModelChoice, ModelPicker } from "./pickers";

/* ── §3 · Build your own benchmark ──────────────────────────────
   A form instead of a YAML file. It produces the exact suite shape the
   existing import endpoint already accepts — the form is a nicer way to
   write the file, not a second format. Checks that need an editor
   (regex, json-schema) stay YAML-only; the form covers the rest. */

type CheckKind =
  | "icontains"
  | "exact"
  | "semantic"
  | "judge"
  | "llm-rubric"
  | "faithfulness"
  | "context-recall"
  | "latency"
  | "cost"
  | "refuse"
  | "allow";

const CHECKS: {
  id: CheckKind;
  label: string;
  needs: ("expected" | "threshold" | "criteria" | "context" | "max_ms" | "max_usd")[];
  threshold?: number;
}[] = [
  { id: "icontains", label: explainAssertion({ type: "icontains", passed: true, score: 1, detail: "" }), needs: ["expected"] },
  { id: "exact", label: explainAssertion({ type: "exact", passed: true, score: 1, detail: "" }), needs: ["expected"] },
  { id: "semantic", label: explainAssertion({ type: "semantic", passed: true, score: 1, detail: "" }), needs: ["expected", "threshold"], threshold: 0.8 },
  { id: "judge", label: explainAssertion({ type: "judge", passed: true, score: 1, detail: "" }), needs: ["expected", "threshold"], threshold: 0.6 },
  { id: "llm-rubric", label: explainAssertion({ type: "llm-rubric", passed: true, score: 1, detail: "" }), needs: ["criteria", "threshold"], threshold: 0.6 },
  { id: "faithfulness", label: explainAssertion({ type: "faithfulness", passed: true, score: 1, detail: "" }), needs: ["context", "threshold"], threshold: 0.8 },
  { id: "context-recall", label: explainAssertion({ type: "context-recall", passed: true, score: 1, detail: "" }), needs: ["context", "expected", "threshold"], threshold: 0.8 },
  { id: "latency", label: explainAssertion({ type: "latency", passed: true, score: 1, detail: "" }), needs: ["max_ms"] },
  { id: "cost", label: explainAssertion({ type: "cost", passed: true, score: 1, detail: "" }), needs: ["max_usd"] },
  { id: "refuse", label: "Safety — the model should refuse this", needs: [] },
  { id: "allow", label: "Safety — the model should answer this, not refuse", needs: [] },
];

type Draft = {
  name: string;
  prompt: string;
  expected: string;
  category: string;
  check: CheckKind;
  threshold: string;
  criteria: string;
  context: string;
  max_ms: string;
  max_usd: string;
};

const blank = (): Draft => ({
  name: "",
  prompt: "",
  expected: "",
  category: "general",
  check: "icontains",
  threshold: "",
  criteria: "",
  context: "",
  max_ms: "10000",
  max_usd: "0.01",
});

/** The form → the suite shape the import endpoint already takes. */
function toSuite(
  name: string,
  description: string,
  model: ModelChoice,
  drafts: Draft[]
) {
  const tests = drafts.map((d, i) => {
    const spec = CHECKS.find((c) => c.id === d.check)!;
    const base: Record<string, unknown> = {
      name: d.name.trim() || `test-${i + 1}`,
      prompt: d.prompt.trim(),
      expected: d.expected.trim(),
      category: d.category.trim() || "general",
    };
    if (d.check === "refuse" || d.check === "allow") {
      base.evaluator = "security";
      base.expected = d.check === "refuse" ? "refusal" : "safe";
      return base;
    }
    const a: Record<string, unknown> = { type: d.check };
    if (spec.needs.includes("expected")) a.value = d.expected.trim();
    if (spec.needs.includes("criteria")) a.criteria = d.criteria.trim();
    if (spec.needs.includes("threshold"))
      a.threshold = d.threshold ? Number(d.threshold) : spec.threshold;
    if (spec.needs.includes("max_ms")) a.max_ms = Number(d.max_ms);
    if (spec.needs.includes("max_usd")) a.max_usd = Number(d.max_usd);
    if (spec.needs.includes("context"))
      base.context = d.context
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);
    base.assert = [a];
    return base;
  });
  return {
    name: name.trim(),
    description: description.trim() || null,
    provider: model.provider,
    model: model.model || "llama3.1",
    evaluator: "exact",
    temperature: 0,
    samples: 1,
    tests,
  };
}

export default function BuildBenchmark({
  onCreated,
  defaultModel,
}: {
  onCreated: (id: string, name: string) => void;
  defaultModel: ModelChoice;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<ModelChoice>(defaultModel);
  const [drafts, setDrafts] = useState<Draft[]>([blank()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update(i: number, patch: Partial<Draft>) {
    setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  }

  const valid =
    name.trim().length > 0 &&
    drafts.length > 0 &&
    drafts.every((d) => {
      if (!d.prompt.trim()) return false;
      const spec = CHECKS.find((c) => c.id === d.check)!;
      if (spec.needs.includes("expected") && !d.expected.trim()) return false;
      if (spec.needs.includes("criteria") && !d.criteria.trim()) return false;
      if (spec.needs.includes("context") && !d.context.trim()) return false;
      return true;
    });

  async function save() {
    setError(null);
    setBusy(true);
    try {
      const suite = toSuite(name, description, model, drafts);
      const r = await importSuite(suite);
      onCreated(r.id, suite.name);
      setOpen(false);
      setName("");
      setDrafts([blank()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="panel flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-sm">
            <span className="font-medium">Have your own tests?</span> Build a
            benchmark without writing YAML.
          </p>
          <p className="text-xs text-muted">
            Prompt, expected answer, the check to apply. Add as many as you
            like. It becomes one of your benchmarks above.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={() => setOpen(true)}>
          Build a benchmark
        </button>
      </div>
    );
  }

  return (
    <div className="panel space-y-4 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="label-xs block" htmlFor="bb-name">
            Benchmark name
          </label>
          <input
            id="bb-name"
            className="field text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Customer support answers"
          />
        </div>
        <div className="space-y-1">
          <span className="label-xs block">Default model</span>
          {/* "bb-model": the picker makes `${prefix}-name`, and "bb-name" is the
              benchmark name field above — two elements with one id, and the
              model label pointed at the wrong one. */}
          <ModelPicker value={model} onChange={setModel} idPrefix="bb-model" />
        </div>
      </div>
      <div className="space-y-1">
        <label className="label-xs block" htmlFor="bb-desc">
          What does it measure? <span className="normal-case">(optional)</span>
        </label>
        <input
          id="bb-desc"
          className="field text-sm"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. Whether answers to billing questions stay polite and quote the right refund window"
        />
      </div>

      <div className="space-y-3">
        {drafts.map((d, i) => {
          const spec = CHECKS.find((c) => c.id === d.check)!;
          return (
            <div key={i} className="space-y-2 border border-line p-3">
              <div className="flex items-baseline justify-between">
                <span className="label-xs">test {i + 1}</span>
                {drafts.length > 1 && (
                  <button
                    type="button"
                    className="label-xs text-muted hover:text-error"
                    onClick={() => setDrafts((ds) => ds.filter((_, j) => j !== i))}
                  >
                    remove
                  </button>
                )}
              </div>

              <div className="grid gap-2 sm:grid-cols-[1fr_10rem]">
                <input
                  className="field text-sm"
                  placeholder="test name (optional)"
                  value={d.name}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
                <input
                  className="field font-mono text-xs"
                  placeholder="category"
                  value={d.category}
                  onChange={(e) => update(i, { category: e.target.value })}
                />
              </div>

              <textarea
                className="field h-20 resize-y text-sm"
                placeholder="Prompt — what you ask the model"
                value={d.prompt}
                onChange={(e) => update(i, { prompt: e.target.value })}
              />

              <select
                className="field text-sm"
                value={d.check}
                onChange={(e) => update(i, { check: e.target.value as CheckKind })}
              >
                {CHECKS.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>

              {spec.needs.includes("expected") && (
                <textarea
                  className="field h-16 resize-y text-sm"
                  placeholder="Expected answer"
                  value={d.expected}
                  onChange={(e) => update(i, { expected: e.target.value })}
                />
              )}
              {spec.needs.includes("criteria") && (
                <textarea
                  className="field h-16 resize-y text-sm"
                  placeholder="Grading criteria — what a good answer must do"
                  value={d.criteria}
                  onChange={(e) => update(i, { criteria: e.target.value })}
                />
              )}
              {spec.needs.includes("context") && (
                <textarea
                  className="field h-24 resize-y font-mono text-xs"
                  placeholder="Source passages the model should rely on — one per line"
                  value={d.context}
                  onChange={(e) => update(i, { context: e.target.value })}
                />
              )}
              <div className="flex flex-wrap gap-3">
                {spec.needs.includes("threshold") && (
                  <label className="flex items-baseline gap-2 text-xs text-muted">
                    pass at
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      className="field w-20 font-mono text-xs"
                      placeholder={String(spec.threshold)}
                      value={d.threshold}
                      onChange={(e) => update(i, { threshold: e.target.value })}
                    />
                    or above
                  </label>
                )}
                {spec.needs.includes("max_ms") && (
                  <label className="flex items-baseline gap-2 text-xs text-muted">
                    within
                    <input
                      type="number"
                      className="field w-24 font-mono text-xs"
                      value={d.max_ms}
                      onChange={(e) => update(i, { max_ms: e.target.value })}
                    />
                    ms
                  </label>
                )}
                {spec.needs.includes("max_usd") && (
                  <label className="flex items-baseline gap-2 text-xs text-muted">
                    under $
                    <input
                      type="number"
                      step="0.001"
                      className="field w-24 font-mono text-xs"
                      value={d.max_usd}
                      onChange={(e) => update(i, { max_usd: e.target.value })}
                    />
                  </label>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setDrafts((ds) => [...ds, blank()])}
        >
          + Add test
        </button>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[11px] text-muted">
            regex and json-schema checks: edit as YAML
          </span>
          <button className="btn btn-ghost" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={save} disabled={!valid || busy}>
            {busy ? "Saving…" : `Create benchmark · ${drafts.length} test${drafts.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}
