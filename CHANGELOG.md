# Changelog

All notable changes to EvalBench. Versions follow the shape of
[Keep a Changelog](https://keepachangelog.com/); dates are release dates.

## [Unreleased]

### Added
- **GitHub Action + PR-comment bot.** `evalbench run --report <file>`
  writes a machine-readable JSON (`summary` + `regression` + `gate`).
  `evalbench pr-comment --report <file>` renders it as Markdown and
  creates/updates a marker comment on the PR. `.github/actions/evalbench`
  is a composite action that stands up an ephemeral EvalBench, runs a
  suite, fails the check on a low pass rate or a regression, and posts the
  comment. Example workflow `.github/workflows/pr-eval.yml`; hosted CI
  suite `suites/ci-hosted.yaml` (no local model needed).

## [0.4.0] — provider abstraction, cost, async jobs, assertions, baselines

### Added
- **Provider abstraction** (`evalbench/core/providers`). One interface over
  Ollama and any OpenAI-compatible host. Presets for `groq`, `gemini`,
  `github`, `openrouter`, `openai` resolve a base URL + API key from
  settings/env; a missing key fails with the exact variable to set. A
  `mock` provider for offline tests. `TestSuite.provider` selects it.
- **Cost & token tracking** (`evalbench/pricing.py`). Per-model token
  rates → estimated USD per test and per run. New `TestResult` fields
  `prompt_tokens`, `completion_tokens`, `cost_usd`; new metrics
  `evalbench_run_cost_usd`, `evalbench_cost_usd_total`,
  `evalbench_prompt_tokens_total`; CLI shows tokens in/out and estimated
  cost; a **Cost & Token Usage** row on the Grafana dashboard.
- **Concurrent execution.** `TestSuite.concurrency` (default 4) runs tests
  in parallel via `asyncio.gather` + a semaphore, capped by a per-provider
  ceiling so free-tier rate limits are respected. Result order preserved.
- **Async job model.** `POST /suites/{id}/run` returns `202 {run_id,
  status:"queued"}` immediately and executes in the background;
  `GET /runs/{id}/status` reports `queued → running → completed | failed`
  with `progress`. CLI and Streamlit poll it with a progress bar. On
  startup the API reaps runs orphaned by a crash.
- **Composable assertions** (`evalbench/core/assertions.py`). A test can
  declare a list of assertions under the YAML key `assert`; all must
  pass. Types: `exact`, `equals`, `contains`, `icontains`, `regex`,
  `semantic`, `judge`, `llm-rubric` (CoT grading vs explicit criteria,
  stores reasoning), `json-schema`, `latency`, `cost`. Legacy
  `evaluator`/`expected`/`threshold` suites get one assertion synthesised.
  Per-assertion results stored on each `TestResult`; `/runs/{id}/summary`
  rolls up pass/fail per type.
- **Baselines & regression-as-a-gate.** `TestSuite.baseline_run_id`;
  `POST /suites/{id}/baseline` and `evalbench baseline <suite> <run>`
  promote a run. `evalbench run --compare-to-baseline` runs the paired
  regression check and exits non-zero on a detected regression. The
  regression result now includes a `per_test` breakdown with a
  `regressed` flag per case.
- Split LLM judge/security graders can run on a different provider than
  the model under test (`judge_provider`, `judge_model`).
- Example suites: `assertions.yaml`, `groq-hosted.yaml`, `ollama-local.yaml`.

### Changed
- The runner dispatches assertions instead of a single evaluator;
  `security` stays a dedicated path.
- `docker-compose.yml` passes hosted-provider keys into the `api`
  container.
- README rewritten for providers, assertions, cost, jobs, baselines.

## [0.3.0] — scoring v2

### Added
- Per-test repeated sampling (`samples`) with majority-vote pass and
  `score_std`; suite-level `temperature`; per-test `evaluator` /
  `category` / `difficulty` overrides; `threshold` wired into `semantic`
  and `judge` cutoffs.
- `by_category` breakdown in `/runs/{id}/summary`; per-category Prometheus
  metrics and a Grafana "Capability by Category" row.

### Fixed
- Fully-errored tests are excluded from `pass_rate` and never trigger a
  false regression.
- `evalbench_security_score` reflects only safety-evaluated tests.
- CLI forces UTF-8 stdout so Rich glyphs don't crash legacy Windows
  consoles.

## [0.1.0] — foundation

Initial release: FastAPI + MongoDB + Ollama + Redis + Streamlit +
Prometheus + Grafana, Typer CLI, JWT/API-key auth with rate limiting,
`exact`/`contains`/`semantic`/`judge`/`security` evaluators, paired-t-test
regression detection, built-in adversarial suite.
