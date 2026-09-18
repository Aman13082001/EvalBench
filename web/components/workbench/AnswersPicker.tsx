"use client";

import { useRef, useState } from "react";
import { AnswerRow, parseAnswers } from "@/lib/answers";

/* ── Bring your own answers ──────────────────────────────────────
   Score outputs the visitor already has. No model is called for
   generation; the file becomes the recording the replay provider
   serves. Only checks that ask an LLM to grade still need a model,
   and the run form asks for that separately.

   The file is parsed here, before any request, so a typo comes back
   with the row named rather than as a run that never answered. */

export type AnswersState = {
  rows: AnswerRow[];
  label: string;
  source: string; // "file.jsonl" or "pasted"
};

export function AnswersPicker({
  value,
  onChange,
  expectedTests,
}: {
  value: AnswersState | null;
  onChange: (v: AnswersState | null) => void;
  /** How many tests the chosen benchmark has, to say how many are covered. */
  expectedTests?: number;
}) {
  const [pasted, setPasted] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function load(text: string, source: string) {
    setErr(null);
    try {
      const rows = parseAnswers(text, source);
      const stem = source.replace(/\.[^.]+$/, "");
      onChange({
        rows,
        label: value?.label || (source === "pasted" ? "" : stem),
        source,
      });
    } catch (e) {
      onChange(null);
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function onFile(f: File | undefined) {
    if (!f) return;
    load(await f.text(), f.name);
  }

  const byName = value?.rows.filter((r) => r.test_name).length ?? 0;
  const byPrompt = (value?.rows.length ?? 0) - byName;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="btn btn-ghost cursor-pointer text-sm">
          Choose file
          <input
            ref={fileRef}
            type="file"
            accept=".json,.jsonl,.csv,.tsv,application/json,text/csv"
            className="sr-only"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </label>
        <span className="font-mono text-[11px] text-muted">
          JSON · JSON Lines · CSV — each row a <span className="text-text">response</span>{" "}
          with a <span className="text-text">test_name</span> or{" "}
          <span className="text-text">prompt</span>
        </span>
      </div>

      <details className="group">
        <summary className="label-xs cursor-pointer select-none hover:text-text">
          or paste
        </summary>
        <div className="mt-2 space-y-2">
          <textarea
            className="field h-32 resize-y font-mono text-xs leading-relaxed"
            spellCheck={false}
            placeholder={'{"test_name": "capital", "response": "Paris"}\n{"test_name": "sum", "response": "4"}'}
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-ghost text-sm"
            disabled={!pasted.trim()}
            onClick={() => load(pasted, "pasted")}
          >
            Use these
          </button>
        </div>
      </details>

      {err && <p className="text-xs text-error">{err}</p>}

      {value && (
        <div className="space-y-2 border-t border-line pt-3">
          <p className="font-mono text-[11px] text-muted tnum">
            <span className="text-success">✓</span> {value.rows.length} answers from{" "}
            <span className="text-text">{value.source}</span>
            {byName > 0 && byPrompt > 0
              ? ` · ${byName} matched by name, ${byPrompt} by prompt`
              : byPrompt > 0
                ? " · matched by prompt"
                : " · matched by test name"}
            {expectedTests !== undefined && value.rows.length < expectedTests && (
              <span className="text-warning">
                {" "}· {expectedTests - value.rows.length} of {expectedTests} tests will have no answer
              </span>
            )}
          </p>
          <div className="grid gap-1 sm:grid-cols-[8rem_1fr] sm:items-baseline">
            <label className="label-xs" htmlFor="answers-label">
              Label this run
            </label>
            <input
              id="answers-label"
              className="field font-mono text-sm"
              placeholder="e.g. my-model-v2 — what produced these answers"
              value={value.label}
              onChange={(e) => onChange({ ...value, label: e.target.value })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
