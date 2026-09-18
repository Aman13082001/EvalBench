"""Study: how much of a judged score is the judge?

Design: research/judge-variance/DESIGN.md. Three stages, each its own
subcommand so the expensive one can be spread across days:

    python scripts/run_study_judge.py generate
        Answer suites/research-judge.yaml once with a strong and a weak
        model. 60 calls, once, ever: the answers are frozen to
        research/judge-variance/answers-{strong,weak}.jsonl and the
        command refuses to overwrite them.

    python scripts/run_study_judge.py score [--repeats 5] [--judge MODEL]
        Every judge scores every frozen answer `repeats` times, with the
        production prompt (evalbench.core.assertions.rubric_prompt), the
        production call (LLMJudgeEvaluator._ask_judge, temperature 0.1)
        and the production parser (parse_judge_output). One line per
        call to scores.jsonl, raw reply included, written as it lands;
        re-running fills whatever is missing. 900 calls at K = 5.

    python scripts/run_study_judge.py analyze
        Arithmetic only. Two-way random-effects decomposition, per-judge
        test-retest, between-judge agreement, the judge floor beside the
        model gap. Writes study.json, judge-spread.svg, REPORT.md, and
        copies the JSON into web/lib/fixtures/ for the research page.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import re
import shutil
import statistics
import sys
import time
from datetime import date, datetime, timezone

import yaml

from evalbench.core.assertions import _extract_json_obj, rubric_prompt
from evalbench.core.evaluators.judge import LLMJudgeEvaluator, parse_judge_output
from evalbench.core.providers import get_provider
from evalbench.db.schemas import TestSuite

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites" / "research-judge.yaml"
OUT = ROOT / "research" / "judge-variance"
FIXTURES = ROOT / "web" / "lib" / "fixtures"

PROVIDER = "groq"
ANSWERERS = {"strong": "openai/gpt-oss-120b", "weak": "allam-2-7b"}
JUDGES = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
PASS_CUTOFF = 0.6  # the llm-rubric default: 3 of 5


# ── files ─────────────────────────────────────────────────────────────


def _answers_path(which: str) -> pathlib.Path:
    return OUT / f"answers-{which}.jsonl"


def _scores_path() -> pathlib.Path:
    return OUT / "scores.jsonl"


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: pathlib.Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def _suite() -> TestSuite:
    return TestSuite(**yaml.safe_load(SUITE.read_text(encoding="utf-8")))


# ── stage 1: generate once ────────────────────────────────────────────


async def _answer_all(suite: TestSuite, which: str, model: str) -> list[dict]:
    provider = get_provider(PROVIDER)
    sem = asyncio.Semaphore(4)
    rows: list[dict] = []

    async def one(t):
        async with sem:
            r = await provider.generate(model, t.prompt, temperature=suite.temperature)
            rows.append({
                "test_name": t.name,
                "category": t.category,
                "prompt": t.prompt,
                "response": r.text,
                "model": model,
                "latency_ms": round(r.latency_ms, 1),
                "tokens": r.total_tokens,
            })
            print(f"  {which:6} {t.name:32} {len(r.text):5} chars")

    try:
        await asyncio.gather(*(one(t) for t in suite.tests))
    finally:
        await provider.close()
    order = {t.name: i for i, t in enumerate(suite.tests)}
    rows.sort(key=lambda r: order[r["test_name"]])
    return rows


async def generate() -> None:
    suite = _suite()
    OUT.mkdir(parents=True, exist_ok=True)
    for which, model in ANSWERERS.items():
        path = _answers_path(which)
        if path.exists():
            print(f"{path.name} exists — frozen, not regenerating.")
            continue
        rows = await _answer_all(suite, which, model)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(rows)} answers, {model})")


# ── stage 2: score, resumably ─────────────────────────────────────────


def _classify(raw: str) -> str:
    """How the production parser read the reply. 'fallback' means it
    found nothing and returned 3/5 — that is not a judgement and is
    kept out of the variance arithmetic."""
    obj = _extract_json_obj(raw)
    if obj is not None and ("score" in obj or "rating" in obj):
        return "json"
    if re.search(r"SCORE:\s*\d", raw, re.IGNORECASE):
        return "score-line"
    if re.search(r"\b[1-5](?:\.\d+)?\b", raw):
        return "digit"
    return "fallback"


async def score(repeats: int, only_judge: str | None) -> None:
    suite = _suite()
    criteria = {t.name: (t.assert_[0].criteria or "") for t in suite.tests}
    answers = {w: _read_jsonl(_answers_path(w)) for w in ANSWERERS}
    for w, rows in answers.items():
        if not rows:
            sys.exit(f"no {w} answers — run `generate` first")

    done = {
        (r["set"], r["test_name"], r["judge"], r["repeat"])
        for r in _read_jsonl(_scores_path())
        if r.get("error") is None
    }
    judges = [only_judge] if only_judge else JUDGES
    todo = [
        (w, a, j, r)
        for r in range(repeats)
        for w in ANSWERERS
        for a in answers[w]
        for j in judges
        if (w, a["test_name"], j, r) not in done
    ]
    print(f"{len(done)} scored already, {len(todo)} to go")
    if not todo:
        return

    # One provider per judge model: Groq's limits are per model, and the
    # provider's shared backoff would otherwise pause all three for a
    # 429 that only one of them earned.
    providers = {j: get_provider(PROVIDER) for j in judges}
    sems = {j: asyncio.Semaphore(2) for j in judges}
    started = time.time()
    n_done = 0

    async def one(w: str, a: dict, j: str, r: int) -> None:
        nonlocal n_done
        prompt = rubric_prompt(a["prompt"], criteria[a["test_name"]], a["response"])
        ev = LLMJudgeEvaluator(judge_model=j, provider=providers[j])
        row = {
            "set": w, "test_name": a["test_name"], "category": a["category"],
            "judge": j, "repeat": r, "at": datetime.now(timezone.utc).isoformat(),
        }
        async with sems[j]:
            t0 = time.time()
            try:
                raw = await ev._ask_judge(prompt)
                s01, reason = parse_judge_output(raw)
                row.update({
                    "score": s01, "score_1_5": round(s01 * 5, 2), "reason": reason,
                    "parsed": _classify(raw), "raw": raw, "error": None,
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                })
            except Exception as e:  # noqa: BLE001 - record and move on
                row.update({"score": None, "error": f"{type(e).__name__}: {e}"[:300]})
        _append_jsonl(_scores_path(), row)
        n_done += 1
        if n_done % 25 == 0 or n_done == len(todo):
            el = time.time() - started
            print(f"  {n_done}/{len(todo)}  {el/60:4.1f} min  {j.split('/')[-1]:>16}  {w}/{a['test_name']}")

    try:
        await asyncio.gather(*(one(*t) for t in todo))
    finally:
        for p in providers.values():
            await p.close()

    errors = [r for r in _read_jsonl(_scores_path()) if r.get("error")]
    if errors:
        print(f"{len(errors)} calls errored (kept in scores.jsonl); run `score` again to fill them")


# ── stage 3: arithmetic ───────────────────────────────────────────────


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def _var(xs):
    return statistics.variance(xs) if len(xs) > 1 else 0.0


def _harmonic(xs):
    return len(xs) / sum(1 / x for x in xs)


def decompose(cells: dict[tuple[str, str], list[float]], answers: list[str], judges: list[str]) -> dict:
    """Two-way random effects: answer × judge with repeats in each cell.

    Cell means carry the crossed structure; the residual is pooled
    within-cell variance. Mild imbalance (a retried cell short a repeat)
    is handled with the harmonic mean of cell sizes, which is the usual
    approximation and exact when balanced.
    """
    a, j = len(answers), len(judges)
    m = {c: _mean(v) for c, v in cells.items()}
    grand = _mean(list(m.values()))
    ans_mean = {x: _mean([m[(x, y)] for y in judges]) for x in answers}
    jud_mean = {y: _mean([m[(x, y)] for x in answers]) for y in judges}
    kbar = _harmonic([len(v) for v in cells.values()])

    ss_e = sum(sum((s - m[c]) ** 2 for s in v) for c, v in cells.items())
    df_e = sum(len(v) - 1 for v in cells.values())
    ms_e = ss_e / df_e if df_e else 0.0
    ms_a = j * kbar * sum((ans_mean[x] - grand) ** 2 for x in answers) / (a - 1)
    ms_j = a * kbar * sum((jud_mean[y] - grand) ** 2 for y in judges) / (j - 1)
    ms_aj = kbar * sum(
        (m[(x, y)] - ans_mean[x] - jud_mean[y] + grand) ** 2 for x in answers for y in judges
    ) / ((a - 1) * (j - 1))

    v_e = ms_e
    v_aj = max(0.0, (ms_aj - ms_e) / kbar)
    v_a = max(0.0, (ms_a - ms_aj) / (j * kbar))
    v_j = max(0.0, (ms_j - ms_aj) / (a * kbar))
    total = v_a + v_j + v_aj + v_e or 1.0
    comp = {"answer": v_a, "judge": v_j, "answer_x_judge": v_aj, "retest": v_e}
    return {
        "variance": {k: round(v, 6) for k, v in comp.items()},
        "share": {k: round(v / total, 4) for k, v in comp.items()},
        "sd": {k: round(math.sqrt(v), 4) for k, v in comp.items()},
        "grand_mean": round(grand, 4),
        "judge_means": {y: round(jud_mean[y], 4) for y in judges},
        "repeats_harmonic": round(kbar, 3),
    }


def analyze() -> None:
    from scipy.stats import spearmanr

    rows = [r for r in _read_jsonl(_scores_path()) if r.get("error") is None]
    if not rows:
        sys.exit("no scores — run `score` first")
    fallback = [r for r in rows if r.get("parsed") == "fallback"]
    clean = [r for r in rows if r.get("parsed") != "fallback"]
    judges = sorted({r["judge"] for r in clean}, key=JUDGES.index)
    answers = sorted({(r["set"], r["test_name"]) for r in clean})
    categories = {(r["set"], r["test_name"]): r["category"] for r in clean}

    cells: dict[tuple, list[float]] = {}
    for r in clean:
        cells.setdefault(((r["set"], r["test_name"]), r["judge"]), []).append(r["score"])
    missing = [(x, y) for x in answers for y in judges if (x, y) not in cells]
    if missing:
        sys.exit(f"{len(missing)} answer×judge cells have no clean score; run `score` again")

    comp = decompose(cells, answers, judges)

    # per-judge test-retest
    retest = {}
    for y in judges:
        means = [_mean(cells[(x, y)]) for x in answers]
        within = [cells[(x, y)] for x in answers]
        k = _harmonic([len(w) for w in within])
        ms_b = k * _var(means)
        ms_w = _mean([_var(w) for w in within])
        icc = (ms_b - ms_w) / (ms_b + (k - 1) * ms_w) if (ms_b + (k - 1) * ms_w) > 0 else float("nan")
        moved = sum(1 for w in within if max(w) - min(w) >= 0.2)  # one rubric point
        flipped = sum(1 for w in within if any(s >= PASS_CUTOFF for s in w) and any(s < PASS_CUTOFF for s in w))
        retest[y] = {
            "icc": round(icc, 4),
            "retest_sd": round(math.sqrt(ms_w), 4),
            "answers_that_moved_a_point": moved,
            "answers_whose_verdict_flipped": flipped,
            "n_answers": len(answers),
        }

    # between-judge agreement on per-answer means
    per_answer = {y: [_mean(cells[(x, y)]) for x in answers] for y in judges}
    agreement = []
    for i, y1 in enumerate(judges):
        for y2 in judges[i + 1:]:
            rho = spearmanr(per_answer[y1], per_answer[y2]).correlation
            mad = _mean([abs(p - q) for p, q in zip(per_answer[y1], per_answer[y2], strict=True)])
            same_verdict = _mean([
                float((p >= PASS_CUTOFF) == (q >= PASS_CUTOFF))
                for p, q in zip(per_answer[y1], per_answer[y2], strict=True)
            ])
            agreement.append({
                "a": y1, "b": y2, "spearman": round(float(rho), 4),
                "mean_abs_diff": round(mad, 4), "same_verdict": round(same_verdict, 4),
            })

    # the gap each judge sees, and the floor beside it
    n = len({x[1] for x in answers})  # tests per set
    gap = {}
    for y in judges:
        s = _mean([_mean(cells[(x, y)]) for x in answers if x[0] == "strong"])
        w = _mean([_mean(cells[(x, y)]) for x in answers if x[0] == "weak"])
        ps = _mean([float(_mean(cells[(x, y)]) >= PASS_CUTOFF) for x in answers if x[0] == "strong"])
        pw = _mean([float(_mean(cells[(x, y)]) >= PASS_CUTOFF) for x in answers if x[0] == "weak"])
        gap[y] = {"strong": round(s, 4), "weak": round(w, 4), "gap": round(s - w, 4),
                  "strong_pass_rate": round(ps, 4), "weak_pass_rate": round(pw, 4)}
    v = comp["variance"]
    floor = {
        "n_tests": n,
        # one judge, run again: only retest noise, averaged over n tests
        "rerun_same_judge_sd": round(math.sqrt(v["retest"] / n), 4),
        # a different judge: its offset plus its per-answer disagreements
        "switch_judge_sd": round(math.sqrt(v["judge"] + v["answer_x_judge"] / n), 4),
        "observed_gap_mean": round(_mean([g["gap"] for g in gap.values()]), 4),
        "observed_gap_min": round(min(g["gap"] for g in gap.values()), 4),
        "observed_gap_max": round(max(g["gap"] for g in gap.values()), 4),
    }

    # by category: where do judges disagree most
    by_cat = {}
    for c in sorted(set(categories.values())):
        xs = [x for x in answers if categories[x] == c]
        sub = {(x, y): cells[(x, y)] for x in xs for y in judges}
        d = decompose(sub, xs, judges)
        by_cat[c] = {"n_answers": len(xs), "share": d["share"], "sd": d["sd"], "grand_mean": d["grand_mean"]}

    study = {
        "generated": date.today().isoformat(),
        "suite": SUITE.name,
        "answerers": ANSWERERS,
        "judges": judges,
        "n_answers": len(answers),
        "n_tests": n,
        "repeats": comp["repeats_harmonic"],
        "calls": len(rows),
        "parse_fallbacks": len(fallback),
        "components": comp,
        "retest": retest,
        "agreement": agreement,
        "gap": gap,
        "floor": floor,
        "by_category": by_cat,
        "pass_cutoff": PASS_CUTOFF,
    }
    (OUT / "study.json").write_text(json.dumps(study, indent=2), encoding="utf-8")
    (OUT / "judge-spread.svg").write_text(render_svg(cells, answers, judges), encoding="utf-8")
    (OUT / "REPORT.md").write_text(render_report(study), encoding="utf-8")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUT / "study.json", FIXTURES / "judge-study.json")
    print(json.dumps({"components": comp["share"], "floor": floor, "fallbacks": len(fallback)}, indent=2))


# ── plot: every answer, every judge, hand-written SVG ────────────────


_COLOURS = ["#5b8def", "#e0a458", "#6cc28f"]


def render_svg(cells, answers, judges) -> str:
    W, H = 900, 360
    L, R, T, B = 48, 16, 26, 58
    pw, ph = W - L - R, H - T - B
    grand = {x: _mean([_mean(cells[(x, y)]) for y in judges]) for x in answers}
    order = sorted(answers, key=lambda x: grand[x])
    n = len(order)
    step = pw / n
    y_of = lambda s: T + ph * (1 - s)  # noqa: E731
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" font-family="ui-monospace, monospace" font-size="11">',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]
    for s in (0.2, 0.4, 0.6, 0.8, 1.0):
        parts.append(f'<line x1="{L}" x2="{W-R}" y1="{y_of(s):.1f}" y2="{y_of(s):.1f}" stroke="#eee"/>')
        parts.append(f'<text x="{L-6}" y="{y_of(s)+4:.1f}" text-anchor="end" fill="#666">{s:.1f}</text>')
    parts.append(f'<line x1="{L}" x2="{W-R}" y1="{y_of(PASS_CUTOFF):.1f}" y2="{y_of(PASS_CUTOFF):.1f}" stroke="#c44" stroke-dasharray="4 3"/>')
    parts.append(f'<text x="{W-R}" y="{y_of(PASS_CUTOFF)-4:.1f}" text-anchor="end" fill="#c44">pass line</text>')
    for i, x in enumerate(order):
        cx = L + step * (i + 0.5)
        if x[0] == "weak":
            parts.append(f'<rect x="{cx-step/2:.1f}" y="{T}" width="{step:.1f}" height="{ph}" fill="#f6f6f6"/>')
    for i, x in enumerate(order):
        cx = L + step * (i + 0.5)
        for k, y in enumerate(judges):
            v = cells[(x, y)]
            dx = (k - 1) * step * 0.22
            parts.append(f'<line x1="{cx+dx:.1f}" x2="{cx+dx:.1f}" y1="{y_of(max(v)):.1f}" y2="{y_of(min(v)):.1f}" stroke="{_COLOURS[k]}" stroke-width="1.5" opacity="0.55"/>')
            parts.append(f'<circle cx="{cx+dx:.1f}" cy="{y_of(_mean(v)):.1f}" r="2.4" fill="{_COLOURS[k]}"/>')
    lx = L
    for k, y in enumerate(judges):
        parts.append(f'<rect x="{lx}" y="{H-B+18}" width="10" height="10" fill="{_COLOURS[k]}"/>')
        parts.append(f'<text x="{lx+14}" y="{H-B+27}" fill="#333">{y}</text>')
        lx += 14 + 7 * len(y) + 22
    parts.append(f'<rect x="{lx}" y="{H-B+18}" width="10" height="10" fill="#f6f6f6" stroke="#ccc"/>')
    parts.append(f'<text x="{lx+14}" y="{H-B+27}" fill="#333">weak model\'s answer</text>')
    parts.append(f'<text x="{L}" y="{H-B+46}" fill="#666">each column is one answer, sorted by its average score; dot = a judge\'s mean over repeats, bar = the range across repeats</text>')
    parts.append(f'<text x="{L}" y="{T-10}" fill="#333" font-size="12">Sixty answers, three judges, five repeats each</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ── report ────────────────────────────────────────────────────────────


def _pct(x: float) -> str:
    return f"{x*100:.0f}%"


def render_report(s: dict) -> str:
    c = s["components"]
    f = s["floor"]
    short = {j: j.split("/")[-1] for j in s["judges"]}
    lines = [
        "# How much of a judged score is the judge?",
        "",
        "*Measured with EvalBench on sixty frozen answers, three judge models,",
        f"{s['repeats']:.0f} repeats each. Design: DESIGN.md. Raw calls: scores.jsonl.*",
        "",
        f"Run {s['generated']} · suite `{s['suite']}` ({s['n_tests']} tests) · answers from",
        f"`{s['answerers']['strong']}` (strong) and `{s['answerers']['weak']}` (weak) ·",
        f"judges {', '.join(f'`{j}`' for j in s['judges'])} · {s['calls']} judge calls,",
        f"{s['parse_fallbacks']} unparseable replies excluded.",
        "",
        "---",
        "",
        "## Question",
        "",
        "When a benchmark asks an LLM to grade an answer against a rubric, the",
        "number that comes back has two authors: the model that wrote the answer",
        "and the model that graded it. How much of the score is which?",
        "",
        "## Method",
        "",
        "1. Thirty open-ended prompts (explanations, summaries, soft constraints,",
        "   refusals, code review), each with a 1–5 rubric. Two models answered",
        "   once; the sixty answers were frozen to files.",
        "2. Each of three judge models scored every frozen answer repeatedly,",
        "   using EvalBench's production rubric prompt, call and parser — the",
        "   same bytes a user's run sends.",
        "3. Every score is indexed by (answer, judge, repeat) and a two-way",
        "   random-effects decomposition splits the variance four ways.",
        "",
        "## Result",
        "",
        "![Every answer, every judge](judge-spread.svg)",
        "",
        "### Where the variance is",
        "",
        "| component | share | sd (0–1 scale) | meaning |",
        "|---|---:|---:|---|",
        f"| between answers | {_pct(c['share']['answer'])} | {c['sd']['answer']:.3f} | the signal: answers really differ |",
        f"| between judges | {_pct(c['share']['judge'])} | {c['sd']['judge']:.3f} | one judge scores everything higher or lower |",
        f"| answer × judge | {_pct(c['share']['answer_x_judge'])} | {c['sd']['answer_x_judge']:.3f} | judges disagree differently on different answers |",
        f"| retest | {_pct(c['share']['retest'])} | {c['sd']['retest']:.3f} | the same judge, the same answer, a different number |",
        "",
        "### Is one judge repeatable?",
        "",
        "| judge | ICC | retest sd | answers that moved ≥ 1 rubric point | answers whose pass/fail flipped |",
        "|---|---:|---:|---:|---:|",
    ]
    for j, r in s["retest"].items():
        lines.append(
            f"| {short[j]} | {r['icc']:.3f} | {r['retest_sd']:.3f} | "
            f"{r['answers_that_moved_a_point']} of {r['n_answers']} | "
            f"{r['answers_whose_verdict_flipped']} of {r['n_answers']} |"
        )
    lines += [
        "",
        "### Do judges agree with each other?",
        "",
        "| pair | Spearman ρ | mean |Δ| | same pass/fail verdict |",
        "|---|---:|---:|---:|",
    ]
    for p in s["agreement"]:
        lines.append(
            f"| {short[p['a']]} vs {short[p['b']]} | {p['spearman']:.3f} | "
            f"{p['mean_abs_diff']:.3f} | {_pct(p['same_verdict'])} |"
        )
    lines += [
        "",
        "### The gap each judge sees",
        "",
        "| judge | strong mean | weak mean | gap | strong pass rate | weak pass rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for j, g in s["gap"].items():
        lines.append(
            f"| {short[j]} | {g['strong']:.3f} | {g['weak']:.3f} | **{g['gap']:+.3f}** | "
            f"{_pct(g['strong_pass_rate'])} | {_pct(g['weak_pass_rate'])} |"
        )
    lines += [
        "",
        "### The judge floor, beside the model gap",
        "",
        f"For a {f['n_tests']}-test benchmark scored once:",
        "",
        f"- re-running the **same** judge moves the benchmark mean by about **±{f['rerun_same_judge_sd']:.3f}** (retest noise, averaged over {f['n_tests']} tests);",
        f"- switching to a **different** judge moves it by about **±{f['switch_judge_sd']:.3f}** (the judge's offset plus its per-answer disagreements);",
        f"- the strong–weak model gap was **{f['observed_gap_mean']:+.3f}** on average across judges (from {f['observed_gap_min']:+.3f} to {f['observed_gap_max']:+.3f} depending on the judge).",
        "",
    ]
    ratio = f["switch_judge_sd"] / abs(f["observed_gap_mean"]) if f["observed_gap_mean"] else float("inf")
    if ratio < 0.25:
        verdict = "The judge is a small part of the story here: a judge switch moves the mean by well under a quarter of the model gap."
    elif ratio < 0.6:
        verdict = "The judge is a real part of the story: a judge switch moves the mean by a sizeable fraction of the model gap, so a score history spanning a judge change is not comparable without re-scoring."
    else:
        verdict = "The judge is most of the story: a judge switch moves the mean by as much as the difference between the two models. On this benchmark a judged score without the judge's name is not a measurement."
    lines += [verdict, "", "### By category", "", "| category | answers | judge + answer×judge share | retest share | mean |", "|---|---:|---:|---:|---:|"]
    for cat, b in s["by_category"].items():
        lines.append(
            f"| {cat} | {b['n_answers']} | {_pct(b['share']['judge'] + b['share']['answer_x_judge'])} | "
            f"{_pct(b['share']['retest'])} | {b['grand_mean']:.3f} |"
        )
    lines += [
        "",
        "## What this means for a team",
        "",
        "- **A judged score without the judge's name is incomplete.** Record",
        "  `judge_model` with every run; EvalBench does. Compare only within",
        "  one judge, or re-score the old answers with the new judge — which",
        "  bring-your-own-answers exists for.",
        "- **The retest component is the floor on resolution.** No number of",
        "  tests removes a judge's per-answer disagreement with itself below",
        "  `retest_sd / sqrt(n)`; the benchmark page's resolution figure for",
        "  judged benchmarks now includes it.",
        "- **Deterministic checks have none of this.** String, schema and",
        "  semantic checks return the same score every time by construction.",
        "  Where a check can be made deterministic, it should be.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python scripts/run_study_judge.py score --repeats 5   # ~900 Groq calls; resumable",
        "python scripts/run_study_judge.py analyze",
        "```",
        "",
        "The frozen answers are committed; `generate` is only needed to make",
        "new ones, and refuses to overwrite these.",
        "",
    ]
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    sc = sub.add_parser("score")
    sc.add_argument("--repeats", type=int, default=5)
    sc.add_argument("--judge", default=None, help="one judge model only")
    sub.add_parser("analyze")
    args = ap.parse_args()
    if args.cmd == "generate":
        asyncio.run(generate())
    elif args.cmd == "score":
        asyncio.run(score(args.repeats, args.judge))
    else:
        analyze()


if __name__ == "__main__":
    main()
