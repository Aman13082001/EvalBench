# Changelog

All notable changes to EvalBench. Versions follow the shape of
[Keep a Changelog](https://keepachangelog.com/); dates are release dates.

## [0.5.0] — 2026-09-07

### Fixed — a connectedness audit

Traced every module, endpoint, component, export, metric, setting and
suite file against its callers. The codebase was well connected; the
defects were concentrated in the few places nothing reached.

- **The monitoring stack collected nothing.** With the compose default
  `JOB_BACKEND=rq` the runner executes in the worker, so every run metric
  was emitted there — and Prometheus scraped only `api:8000`, while the
  worker had no metrics endpoint at all. All 28 metrics, 9 alert rules
  and the Grafana dashboard were fed by a process nobody read. Nothing
  looked broken: the panels rendered "No data", indistinguishable from an
  idle system. The worker now serves `/metrics` on `WORKER_METRICS_PORT`,
  discovered by `dns_sd_configs` so `--scale worker=N` needs no edit.
- **`GET /suites/{id}/regression-history` leaked other users' runs** — no
  owner filter, while its reachable sibling had one. Unused code is
  unaudited code: nothing called it, so the ownership pass missed it.
- **`POST /suites/{id}/baseline` accepted a run you don't own**, which
  would silently break the suite's own regression gate.
- **The statistics engine was unreachable from the web app.**
  `POST /regression`, `compareRuns()` and `ComparisonReport` all existed
  and nothing connected them, so a user could promote a baseline but
  never compare against it. Wired into `/suites/[id]`.
- **`POST /suites/{id}/compare` removed** — no client, no test, never set
  `created_by` (so its runs were invisible to their creator), and ran
  synchronously inside the request while every other run path is queued.
- Four root files left behind by an old refactor: `action.yml` (a
  strictly-worse copy of the real composite action, and harmful at the
  root), `suite.yaml` and `smoke-test.yaml` (superseded). The fourth,
  `security-test.yaml`, was **not** redundant — its 9 safety categories
  exist nowhere else — and became `suites/safety.yaml`.
- The playground's "12 tests / 3 samples" limits were hardcoded in the
  page copy; `/run` now reads them, and the valid assertion types, from
  `GET /playground/providers`.
- Four metrics were emitted but displayed nowhere — now an
  Instrumentation row on the dashboard.
- ADRs 0001–0003 were written but linked from nothing.

Two structural tests guard the classes of bug rather than the instances:
`test_ownership_coverage.py` fails any API handler that queries owned
data without a guard, and `test_metrics_wiring.py` fails if any service
that can run a suite is not a Prometheus target. Both were verified to
fail against the unpatched code.

The release that turned a CLI + API into a product: a web app anyone can
use, per-user ownership, and an original research study.

### Added — Phase F: the web app (`web/`)
- A Next.js 14 app replacing the Streamlit dashboard. Design system
  **"Laboratory Notebook"** — parchment/ink palette, serif display face,
  tabular monospace numerals, 1px hairlines, `steps()` motion. No
  gradients, no glassmorphism, no shadows. Documented at `/styleguide`.
- **The homepage demonstrates instead of explaining.** `HeroDemo` replays
  a real recorded run as a seven-stage animation: prompt → dispatch →
  streaming response → assertion checks one at a time → aggregate → score
  → statistics. Honours `prefers-reduced-motion`.
- **Plain language first.** `web/lib/explain.ts` renders every assertion,
  score and statistic as a sentence a non-engineer can read, with the raw
  term and threshold behind a disclosure. Written after the observation
  that `pass_rate_ci` and `cosine=0.625` wall off most visitors.
- Pages: `/` demo, `/example` recorded run, `/run` playground with four
  starter presets (quick / every assertion type / RAG / safety),
  `/research` the study, `/login`, `/suites` + `/suites/[id]`,
  `/runs/[id]`, `/dashboard` (embedded Grafana), `/admin`.
- Recorded fixtures rather than live calls on public pages — honest,
  instant, and cannot fail in front of a visitor
  ([ADR 0004](docs/adr/0004-recorded-fixtures-on-the-homepage.md)).

### Added — Phase B7: ownership & administration
- `created_by` on suites and runs; `owner_filter` / `owns` /
  `require_owner` in `evalbench/api/deps.py`. Users see only their own
  resources; admins see everything.
- Someone else's id returns **404, not 403** — the API never confirms the
  existence of a resource it will not serve.
- `evalbench/api/admin.py`: `GET /admin/users` (never returns
  `hashed_password` or `api_key`), activate/deactivate, `GET
  /admin/stats`. An admin cannot deactivate their own account.
- Deactivated users are rejected at authentication with 403.

### Added — research
- `research/REPORT.md`: a bootstrap power analysis of regression
  detection on real paired model outputs. **Power is ~21% at n = 10 and
  reaches 80% only near n ≈ 60** — a ten-prompt suite misses a genuine
  regression about four times in five, failing asymmetrically toward
  false confidence.
- `scripts/run_study_power.py` reproduces it end to end and hand-renders
  the power curve as SVG (no plotting dependency).
- Surfaced in the product as `min_samples_for_5pt_mde` and the bootstrap
  CIs on every run summary.

### Added — documentation
- Four architecture decision records in `docs/adr/`: MongoDB over
  Postgres, an assertion list over a rule DSL, RQ over Celery, and
  recorded fixtures on the homepage.
- `docs/DEPLOY.md`: Vercel + Fly/Railway + Atlas + Upstash, secret
  generation, and the cold-start and Grafana-embedding caveats.
- README rewritten around the web app, ownership and the study.

### Fixed
- **Judge false negatives in `faithfulness` and `context-recall`.** The
  parser treated a missing support field as unsupported, so a grounded
  answer could score 0/3. Judges are now asked to *cite* the numbered
  passage that supports each claim (`"source": <n>`), and the parser
  accepts the citation shape as well as the older booleans. A near-
  verbatim grounded answer scored 0/3 before, correct after.

### Added — Phase C: real job queue
- Run execution extracted to `evalbench/jobs.py` (`execute_run_job` now
  takes just `run_id` + `suite_id` and loads the suite itself).
- `JOB_BACKEND` setting: `inline` (default — FastAPI BackgroundTasks, no
  Redis) or `rq` (enqueue to Redis, run by `python -m evalbench.worker`).
  RQ jobs retry twice on transient failure and survive an API restart;
  add workers with `docker compose up --scale worker=N`.
- `docker compose` gains a `worker` service and defaults to `rq`.
- `/runs/{id}/status` includes `queue_position` while queued (rq).

### Added — Phase D: statistical depth
- `evalbench/core/stats.py`: percentile bootstrap CI, exact McNemar test,
  paired Cohen's d, power-based min-sample estimate.
- `/runs/{id}/summary` returns `pass_rate_ci` / `avg_score_ci` (95%
  bootstrap) — every headline number now has an interval.
- Regression output gains `mcnemar` (the correct test for paired
  pass/fail), `effect_size` (Cohen's d), and `min_samples_for_5pt_mde`
  (is the suite big enough to trust a 5-point move?). Surfaced in
  `evalbench compare` / `--compare-to-baseline`.

### Added — Phase B: RAG evaluation
- `TestCase.context: list[str]` — retrieved passages, threaded to assertions.
- **`faithfulness`** — grounded fraction of the answer's atomic claims
  against `context`; unsupported claims are named.
- **`context-recall`** — fraction of `expected`'s facts present in
  `context` (low = retrieval missed something).
- **`context-precision`** — fraction of retrieved passages relevant to
  the question (low = retrieval noise).
- The LLM grader now returns **structured JSON** (`{"score", "reason"}` /
  claim lists), parsed with the old regex scrape only as a fallback.
- `evalbench_assertion_score` histogram (by assertion type) + a Grafana
  **RAG Assertion Quality** row. Example suite `suites/rag-demo.yaml`.

### Changed — Phase A hardening
- **Auth is now consistent** — every data endpoint requires a user; only
  `/health`, `/live`, `/ready` are public. `tests/test_auth_coverage.py`
  asserts it per route.
- **Refuse to boot on placeholder secrets** — `SECRET_KEY` /
  `ADMIN_PASSWORD` / `ADMIN_API_KEY` at their shipped defaults fail
  startup unless `EVALBENCH_ALLOW_INSECURE=1`.
- **Mongo indexes** created on startup for the hot paths (`users.api_key`,
  `users.username`, `suites.created_at`, `test_runs` (suite_id,
  created_at), `test_runs.status`).
- **Provider 429 backpressure** — `OpenAICompatibleProvider` retries rate
  limits with exponential backoff (honours `Retry-After`); a persistent
  limit raises `RateLimitError` and the runner records the sample as
  `rate_limited`, not `error`. Surfaced in the summary + CLI.
- **Pricing table honesty** — every entry carries `source` + `as_of`;
  `scripts/check_pricing.py` fails CI on stale entries; `evalbench run
  --strict-cost` fails on an unpriced model.
- **First integration test** on a real async Mongo (mongomock-motor) —
  register → run → summary → baseline → regression through the live API.
- Deleted the dead `evalbench/core/models.py` shim.

### Added
- **GitHub Action + PR-comment bot.** `evalbench run --report <file>`
  writes a machine-readable JSON (`summary` + `regression` + `gate`).
  `evalbench pr-comment --report <file>` renders it as Markdown and
  creates/updates a marker comment on the PR. `.github/actions/evalbench`
  is a composite action that stands up an ephemeral EvalBench, runs a
  suite, fails the check on a low pass rate or a regression, and posts the
  comment. Example workflow `.github/workflows/pr-eval.yml`; hosted CI
  suite `suites/ci-hosted.yaml` (no local model needed).

### Removed
- The Streamlit UI (`frontend/`) and its compose service, superseded by
  the Next.js app.

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
