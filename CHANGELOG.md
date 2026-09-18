# Changelog

All notable changes to EvalBench. Versions follow the shape of
[Keep a Changelog](https://keepachangelog.com/); dates are release dates.

## [Unreleased]

### Added — evaluate your own endpoint

A model that is not in the list can still be measured: `provider: custom`
with a `base_url` points a run at any OpenAI-compatible server — a
vLLM, Ollama behind a tunnel, a gateway, a fine-tune you host. The key
is optional (a personal server behind a tunnel often has none) and it
travels the same encrypted, short-lived road as any caller key; the
server's own keys are never sent there, and nothing counts against the
daily cap. `evalbench run --base-url … [--endpoint-key …]` on the CLI;
"My own endpoint" in the workbench and the comparison, where A and B
can be two different servers. Supplied answers can be graded on one
too (`judge_provider: custom`).

A URL a stranger typed, fetched by the server, is server-side request
forgery unless it is made not to be. `evalbench/core/endpoint.py`:

- The URL is checked at submission — https only, a host and nothing
  else (no `user:pass@`, no query), and every address it resolves to
  must be public — and refused with the reason as a 400, not a dead run.
- The check happens again *inside* the connection. A hostname can
  resolve to a public address when checked and to `127.0.0.1` when
  dialled; `PinnedBackend` resolves, checks every answer, and opens the
  socket to the address it approved. There is no second resolution to
  rebind. TLS still verifies against the hostname.
- Redirects are never followed, an environment proxy cannot route
  around the pin, and a response is cut off past 8 MB. A refusal never
  echoes what an internal name resolved to — on a public instance that
  would be a map of the network, one request at a time.
- `ALLOW_PRIVATE_ENDPOINTS=true` is the escape hatch for a self-hosted
  instance and a model server on the same LAN. It is documented as
  never-on-a-public-deployment and defaults off.

### Added — bring your own answers

Score outputs you already have. EvalBench scores answers; calling a
model was only ever how an answer arrived, and requiring it locked out
the team with last week's outputs in a CSV, the person whose model is a
notebook with no endpoint, and anyone who will not paste a key into a
stranger's website. It also made a whole class of research impossible:
you cannot separate judge noise from model noise unless you can score
the *same* answers more than once.

- `POST /suites/{id}/run` takes `answers` — JSON array, JSON Lines or
  CSV rows of `{test_name | prompt, response}`, lenient about column
  names — and replays them through the provider that already served the
  demo. The run records `provider: answers`; the label you give it is
  the model name. A row matching no test is refused with its name.
- Only checks that ask an LLM to grade need a model. `suite_needs_judge`
  decides; string, regex, schema, latency, cost and semantic checks run
  with zero calls, no key and no cap. A rubric benchmark names its
  grader (`judge_provider` / `judge_model`) and only the grading counts.
- `evalbench run suite.yaml --answers out.jsonl` on the CLI, validated
  locally before any request. `needs_judge` on every benchmark listing
  so the workbench can hide the grader when there is nothing to grade.
- Latency is reported as not measured, and a missing row reads as "no
  answer in the file you supplied", not as a provider failure.

### Fixed — a judge's worst verdict parsed as its best

Every judge prompt asks for `{"score": <1-5>}`. The parser treated any
score `<= 1.0` as an already-normalised fraction, so a score of **1** —
the lowest a judge can give — came back as **1.0**, the highest. A
rubric check on an answer the judge described as "violates the rubric"
passed with a perfect score. Only 1 inverted; 2 through 5 were fine,
which is why it survived. Found by scoring a hand-written answer that
deliberately did the wrong thing. An integer is now always on the 1-5
scale; only a non-integer strictly between 0 and 1 is read as a
fraction.

### Security — a caller's provider key no longer persists in Redis

- The key travelled to the worker as an RQ job argument. RQ persists job
  arguments — pickled, in `rq:job:<id>` — and keeps a *failed* job at
  its default failure_ttl of one year. Measured on the running stack: a
  failed job's TTL was 31,108,291 seconds. A user who pasted a key and
  hit a rate limit had it in Redis, in plaintext, for 360 days. The
  existing test proved the key never reached Mongo, which was true and
  beside the point.
- `evalbench/runkeys.py`: the key is written once under its own name,
  encrypted with Fernet keyed from `SECRET_KEY`, with a six-hour TTL;
  the job carries only the run id; the worker reads it and deletes it
  once the run cannot need it again (kept only while RQ retries remain).
  The TTL is the guarantee, the delete a courtesy. Jobs queued before
  the change still carry the key as an argument and are honoured.
- Found while verifying: a bring-your-own-key run on a suite whose judge
  is a keyless provider (the demo suite judges on the replay provider)
  crashed with "unexpected keyword argument 'api_key'". `get_provider`
  now drops a supplied key for providers that take none.

### Changed — the dashboard actually shows the dashboard

- **Panels were never rendering.** The embed used
  `/d/<uid>?panelId=N`, which renders the *whole dashboard* and ignores
  `panelId` — so each frame showed a cropped overview or Grafana's home
  screen. Single panels come from `/d-solo/`. Every panel on the page
  was wrong for as long as the page has existed.
- 23 panels instead of 5, laid out full-bleed across seven sections,
  with a time-range control. A 224px timeseries in a text column is not
  an instrument.
- Panels follow the site's theme — including "system", which stamps no
  attribute — instead of being pinned to light inside a dark page, and
  they mount as they are scrolled to, at most a few at a time.
- Grafana draws its own panel title inside the frame; it is clipped so
  the caption above is not repeated in a second typeface.
- Dropped the "Model Health" panel from the page: it queries
  `evalbench_ollama_model_loaded`, so it is permanently empty for any
  hosted provider. The regression pair is kept but labelled as
  populating only after a baseline comparison.
- The gauges had no `displayName`, so each series was labelled with its
  raw selector (`evalbench_pass_rate{e…`). They now read as the suite or
  model they describe.

### Changed — instruments that know their own precision

- **Every benchmark reports what it can resolve.** `mde_for_n` inverts
  the existing power calculation, and `evalbench/resolution.py`
  estimates the spread from the benchmark's own run history — paired by
  test name, errored tests excluded. A benchmark run once reports no
  number and says what is missing, because resolution is an empirical
  property and not a property of the YAML.
- **Rate limits read as what they are.** A run that lost samples but
  answered every test used to announce "0 of 51 tests never got an
  answer". The two conditions are now separate: tests that got no answer
  are missing from the numbers; tests that lost *samples* are in them but
  measured less precisely, and the summary counts them
  (`samples_requested`, `undersampled_tests`). A real run had 25 of 51
  tests scored on fewer than the 3 samples requested.
- **429s pause the provider, not just the request.** A free tier's
  ceiling is per-minute and shared, so four workers retrying in parallel
  burn their attempts against the same shut door. Each 429 now holds
  every in-flight request for the same backoff (`Retry-After` honoured),
  and the retry budget rose from 3 to 5.
- **One definition of a run-history row.** `/runs` and
  `/suites/{id}/runs` counted scored tests by different rules, so the
  same run showed two pass rates depending on the page. Both now call
  `run_row`, which counts as the summary does, and the per-suite history
  stopped shipping whole run documents.
- Run history rows say what the run found — pass rate, tests scored,
  date, samples lost — behind an "Open report →" link, instead of an
  unlabelled Mongo id as the only clickable thing.

### Changed — a benchmark is its name

- **Importing a suite is create-or-update.** `POST /suites/import` (and
  `POST /suites`) look for the caller's suite of the same name and
  update it in place — same id, same run history, same baseline —
  instead of inserting another copy. `evalbench run` imports before
  every run; as a plain insert that left a new suite behind each time,
  and one database reached 70 suites with 18 names. The response says
  which happened: `{"created": true|false}`, 201 or 200.
- **`evalbench merge-suites`** folds the duplicates that already exist:
  one copy kept per (owner, name) — the one holding a baseline, else
  the newest — every run re-pointed at it, the rest deleted. Runs are
  never deleted. Dry run by default; `--apply` writes; `--claim <user>`
  assigns suites from before accounts existed to that user first.
- **Suites carry a `description`.** One or two sentences on what the
  benchmark measures, in the YAML. Every bundled suite has one; the
  workspace picker shows it once a benchmark is chosen, the build form
  asks for it, and the manifest reads it from the file rather than
  keeping its own copy.
- **The benchmarks list is a list.** `GET /suites` sends `test_count`
  instead of the test bodies — it was 129 KB of prompts to print
  "51 tests" — and the page shows name, description and count. Model,
  check type and baseline badges were noise there; they belong to the
  run and the detail page.
- Wording: the pages say *benchmark*, matching the nav. Sign-up lands on
  the Workbench. "sign in" in the nav and on the example page opens the
  same dialog the homepage uses; `/login` remains only as the auth
  redirect target.

### Removed — one way to do each thing

- **`/run`, the public playground.** Everything it did — paste a suite,
  bring a key, run it — the Workbench does with a free account, and does
  better: honest error reporting, a model picker, a daily cap instead of
  a 12-test one. Two ways to run an evaluation meant the weaker one was
  the first thing a visitor found. The `/playground/*` endpoints, their
  TTL collection and tests go with it.
- **The hero demo.** `HeroDemo`, `hero-run.json`, `suites/hero.yaml` and
  `scripts/capture_hero.py` had rendered nothing since the homepage was
  rebuilt around the architecture animation. ADR 0004 is marked
  superseded rather than deleted.
- **`/styleguide`.** A page of colour swatches is not part of the product.
- **"Try" and "Example" from the nav.** The public nav is one link,
  Research; the example evaluation is reached from the end of the study.
  A visitor's path is now home → study → example → sign in → Workbench,
  and every public page has one exit that points forward.

The `demo` provider stays: `evalbench run suites/demo.yaml` still works
with no key at all.

## [0.5.0] — 2026-09-07

### Added — the workbench

The first page after sign-in: evaluate → understand → build → compare.

- `/workbench`: pick a benchmark (bundled, yours, or uploaded YAML), a
  provider and model, and whose key pays; run through the existing job
  endpoint with inline progress. The result block leads with the pass
  rate set large, then the existing `Results` view. A form builds a
  benchmark without YAML, emitting the exact shape `/suites/import` takes.
  Compare-two-models runs one benchmark twice with model overrides and
  hands the pair to `/compare?a=&b=`, which the regression engine renders.
- Backend, minimal: optional `{model, provider, provider_key}` body on
  `POST /suites/{id}/run` (the key reaches the job and is never stored);
  `DAILY_RUN_CAP` per user on server-key runs with `GET /suites/quota`;
  `GET /runs?limit=` across all suites; `GET /suites/bundled` from a
  curated manifest and an idempotent `POST /suites/bundled/{slug}/adopt`.
- `explain_model_comparison` / `explainModelComparison`: symmetric wording
  for two models on one benchmark — including the sentence a raw
  pass-rate comparison never produces, "within expected noise".

### Fixed — found by driving the real UI
- `GET /runs/{id}/summary` omitted per-test `results` while the playground
  summary included them; the result view crashed on first render.
- `ComparisonReport` narrated one recorded fixture ("the smaller model",
  "the drop", "moderate, not large") and stated falsehoods when reused —
  and was wrong for its own fixture (d = −0.49 is small). Every sentence
  is now derived from the data, with a mode for model-vs-model.
- `suites/` had been excluded from the API image as "not needed at
  runtime"; the bundled benchmark list returned `[]` in the container.
- `test_auth_coverage` now walks `app.routes`; the hand list had two
  protected routes nobody recorded.

### Added — after a round of user testing

Three findings from actually using the thing, all valid:

- **Plain language in the CLI.** The web app got `explain.ts` after
  earlier feedback about jargon; the CLI still printed `T-Statistic` /
  `P-Value` / `faithfulness` with no translation, and terminal output is
  what people screenshot. `evalbench/explain.py` mirrors the web wording
  across the run summary, the assertion table and both comparison paths.
  Tests pin meaning as well as tone — a real regression must still read
  bluntly, and one test diffs the two layers so they cannot drift.
- **Anyone can now run an evaluation with no API key.** Every playground
  provider required one, so a visitor landed on a form they could not
  submit. `ReplayProvider` ("demo") serves answers captured from a real
  run while the assertion engine, judge calls, scoring and statistics all
  execute live. `scripts/capture_demo.py` records by running the suite
  for real with every provider call wrapped, which is what catches the
  runtime-generated judge prompts. An unrecorded prompt errors and is
  excluded from the pass rate rather than being invented.
- **`evalbench reset-password`.** An admin who did not know the admin
  password was locked out of `/admin` with no recovery path anywhere.
  Writes directly to MongoDB rather than exposing an endpoint, prints the
  database it targets, and on a miss names the accounts that database
  holds — because a natively installed MongoDB can occupy the same port
  Docker publishes, and "no such user" then means "wrong database".

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
- **The web app was not in `docker compose` at all.** When the Streamlit
  service was removed, nothing replaced it — so `docker compose up`
  brought up the API, worker, Mongo, Redis, Ollama, Prometheus and
  Grafana, and no website. `web/` is now containerized (multi-stage,
  Next standalone output, 225 MB against the old Streamlit image's
  9.1 GB) and comes up with everything else. `NEXT_PUBLIC_API_URL` is a
  build arg, not a runtime env var, because Next inlines it into the
  client bundle — and it has to be the browser-visible address, so
  `http://api:8000` would have looked right and failed for every real
  visitor.
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
