# How much of a judged score is the judge?

*Experiment design, written before anything ran; the budget section
says what each cut costs. K = 5 was chosen. Results: REPORT.md.*

---

## Question

When a benchmark asks an LLM to grade an answer against a rubric, the
number that comes back has two authors: the model that wrote the answer
and the model that graded it. EvalBench's existing study measured how
many tests it takes to detect a regression when every check is
deterministic. This one asks the question that study deliberately
avoided: **when the check is a judge, how much of the score is the
judge?**

Three quantities, in order of how much they should worry a team:

1. **Test–retest.** The same judge, the same answer, the same rubric,
   asked again. How far does the score move? This is the noise a single
   run carries even if nothing else changes.
2. **Between-judge.** Three different judge models on the same answers.
   Do they agree on which answers are good, and on *how* good? A team
   that switches judge models (a deprecation, a cost cut) needs to know
   whether its history is still comparable.
3. **Judge floor vs. model gap.** The strong and weak model differ by
   some amount. Is that amount larger than the judge's own spread? If
   not, a judged benchmark cannot tell the two models apart, no matter
   how many tests it has.

The thesis of the project is that LLM evaluation is itself badly
measured. This is the study that puts a number on the part of the
instrument everyone treats as a constant.

## Design

**Answers are generated once and frozen.** Two models answer a 30-test
suite of open-ended prompts, once each, and the 60 answers are written
to files and committed. Every scoring pass afterwards replays those
files through the bring-your-own-answers path. This is the only way to
separate judge variance from model variance: if the answers changed
between passes, a moving score could be either. It also makes the study
reproducible for zero generation calls.

**Then the same 60 answers are scored repeatedly.** Each of three judge
models scores every answer *K* times, as EvalBench actually runs its
judge: the production prompt (`rubric_prompt`, the same function the
runner calls), the production call (`LLMJudgeEvaluator._ask_judge`,
temperature 0.1) and the production parser (`parse_judge_output`). The
study calls those three directly rather than going through the runner
so that it can keep every raw reply: a reply the parser could not read
comes back as 3/5 in production, and that is a parse failure, not a
judgement — it is counted and excluded, not averaged in.

**Then the scores are decomposed.** Every score is indexed by
(answer, judge, repeat). A two-way random-effects decomposition splits
the total variance into:

| component | what it is | what it means for a team |
|---|---|---|
| between-answer | answers really do differ in quality | the signal — what the benchmark is for |
| between-judge | one judge scores everything higher/lower | a constant offset; harmless *within* one judge, fatal across a judge switch |
| answer × judge | judges disagree *differently* on different answers | the dangerous one — cannot be calibrated away |
| residual (retest) | the same judge, same answer, different number | the noise a single run carries |

From those: the **test–retest ICC** per judge (how repeatable one judge
is), **pairwise agreement** between judges on per-answer mean scores
(Spearman, and mean absolute difference on the 0–1 scale), and the
headline — the **judge floor**: the standard deviation of a 30-test
benchmark's mean score attributable to judge alone, set beside the
observed strong–weak gap.

**The comparison that makes the point.** Deterministic checks — string,
regex, schema, and the locally-computed semantic similarity — return
the same score for the same answer every time, by construction. Their
retest variance is zero and they have no judge term at all. The power
study measured a 30-test suite built only from those. Setting this
study's retest and judge terms beside that zero is the cleanest
statement of what a judge costs, and of why a check should be made
deterministic wherever it can be.

## The suite

`suites/research-judge.yaml`, 30 tests. Prompts where a rubric is the
only honest check — nothing a regex could grade:

- 8 × short explanation ("explain X to a 12-year-old in under 80 words")
- 6 × summarisation (a 150-word passage → 2 sentences)
- 6 × instruction following with a soft constraint ("write a product
  description that never mentions price")
- 5 × refusal / safety judgement (the prompt should be declined; the
  rubric asks whether it was, and whether the decline was useful)
- 5 × code review ("what is wrong with this function") with a known
  defect

Each test has one `llm-rubric` assertion with a 1–5 criterion written
to be gradable. The rubrics are the same for every judge and every
repeat.

Models: answers from `openai/gpt-oss-120b` (strong) and `allam-2-7b`
(weak) — the same pair as the power study, so the gap is already
characterised on deterministic checks. Judges: `openai/gpt-oss-20b`,
`openai/gpt-oss-120b`, `qwen/qwen3.8-27b`. All on the Groq free tier.
(`llama-3.3-70b` is no longer served there; the model list was checked
on 2026-09-19.)

## Budget

Generation: 60 calls, once, ever.

Scoring: 60 answers × 3 judges × *K* repeats. Each judge call is
roughly 350 tokens in, 60 out.

| K | judge calls | per judge model | tokens per judge model | wall time (est.) |
|---:|---:|---:|---:|---:|
| 10 | 1,800 | 600 | ~250k | ~35 min |
| 5 | 900 | 300 | ~125k | ~18 min |
| 3 | 540 | 180 | ~75k | ~11 min |

Groq's free tier limits are per model per day. K = 10 is the design;
K = 5 is the cut that keeps every conclusion (retest ICC is estimable
from 5 repeats; the between-judge and interaction terms do not depend
on K). K = 3 makes the retest estimate rough but still reports the
other three components. The script takes `--repeats` and can run one
judge per invocation (`--judge`), so the passes can be spread across
days without changing the analysis.

Everything else is free: the decomposition is arithmetic on a JSON
file.

## What comes out

- `research/judge-variance/answers-{strong,weak}.jsonl` — the frozen
  answers (committed; the study is re-runnable from these alone).
- `research/judge-variance/scores.jsonl` — one line per judge call:
  set, test, judge, repeat, parsed score, the judge's reason, the raw
  reply, and how the parser read it.
- `research/judge-variance/REPORT.md` — the four components, the
  per-judge ICC, the agreement matrix, the judge floor beside the model
  gap, and a plain-language paragraph on what it means.
- Phase D: each judged benchmark's page shows its **judge-noise floor**
  next to its resolution, and the resolution estimate accounts for it.

## What would falsify the premise

If the residual and interaction terms together are under ~5% of total
variance and the three judges' per-answer means correlate above 0.9,
then judges are a fine instrument and the thesis is wrong for this
class of check. That result gets published the same way.
