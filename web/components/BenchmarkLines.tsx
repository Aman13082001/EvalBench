"use client";

import Link from "next/link";
import type { JudgeFloor, Resolution } from "@/lib/api";

/* The two lines that make a benchmark an instrument rather than a file.

   Resolution is the benchmark's own: the spread between its runs, so a
   benchmark nobody has run twice reports nothing and says why. The judge
   floor is transferred from the judge-variance study and scaled to this
   benchmark's size: what the grader alone does to the mean, whatever the
   run history says. Rendered the same on the list and the detail page. */

export function ResolutionLine({ r }: { r?: Resolution | null }) {
  if (!r) return null;
  if (r.mde === null) {
    return (
      <p className="font-mono text-[11px] text-muted">
        resolution: <span className="italic">{r.reason}</span>
      </p>
    );
  }
  const points = Math.round(r.mde * 100);
  return (
    <p className="font-mono text-[11px] text-muted tnum">
      resolution: detects a drop of{" "}
      <span className="text-text">{points} points</span> or more · 80% power ·
      from {r.runs_used} runs
    </p>
  );
}

export function JudgeFloorLine({ f }: { f?: JudgeFloor | null }) {
  if (!f) return null;
  const pts = (x: number) => {
    const p = x * 100;
    if (p < 1) return "under ±1 point";
    const n = p.toFixed(p < 3 ? 1 : 0);
    return `about ±${n} point${n === "1" || n === "1.0" ? "" : "s"}`;
  };
  return (
    <p className="font-mono text-[11px] text-muted tnum">
      judge floor: the grader alone moves the mean{" "}
      <span className="text-text">{pts(f.rerun)}</span> between runs,{" "}
      <span className="text-text">{pts(f.switch)}</span> across a judge change ·{" "}
      {f.judged === f.tests ? "every test judged" : `${f.judged} of ${f.tests} tests judged`} ·{" "}
      <Link
        href="/research#judge"
        className="underline decoration-line underline-offset-2 hover:text-text"
        onClick={(e) => e.stopPropagation()}
      >
        the study
      </Link>
    </p>
  );
}
