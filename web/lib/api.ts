import { authed } from "./auth";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface CategoryStat {
  total: number;
  passed: number;
  errors: number;
  /** Tests that actually got an answer. */
  scored?: number;
  /** null when nothing in the category could be scored — "no reading",
   *  which is not the same finding as 0%. */
  pass_rate: number | null;
  avg_score: number | null;
}

export interface AssertionOutcome {
  type: string;
  passed: boolean;
  score: number;
  detail: string;
}

export interface TestResult {
  test_name: string;
  prompt: string;
  expected: string;
  actual: string;
  passed: boolean | null;
  score: number | null;
  latency_ms: number;
  cost_usd?: number;
  category?: string | null;
  error?: string | null;
  /** Samples that produced an answer. 0 with an error = the test never
   *  ran (excluded from scoring); >0 with an error = some samples were
   *  lost but the test was still scored on the rest. */
  runs?: number;
  rate_limited?: number;
  assertions?: AssertionOutcome[];
}

export interface RunSummary {
  run_id: string;
  model: string;
  total_tests: number;
  scored_tests: number;
  errors: number;
  passed: number;
  failed: number;
  /* Null when nothing was scored. "0%" would be a measurement —
     every answer wrong — and that is a different claim from having
     measured nothing at all. */
  pass_rate: number | null;
  avg_score: number | null;
  pass_rate_ci: [number, number] | null;
  avg_score_ci: [number, number] | null;
  avg_latency_ms: number | null;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  rate_limited_samples: number;
  /* Samples asked for per test, and how many tests got fewer. Losing a
     sample is not an error — the test was answered — but it costs
     precision, which is otherwise invisible. */
  samples_requested?: number;
  undersampled_tests?: number;
  by_category: Record<string, CategoryStat>;
  assertion_types: Record<string, { passed: number; failed: number }>;
  results: TestResult[];
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/* ────────────────────────────────────────────────────────────────
   Authenticated endpoints. These mirror the API exactly — see
   `evalbench/api/routes.py`, `main.py` and `admin.py`.
   ──────────────────────────────────────────────────────────────── */


/* What a benchmark can actually detect, measured from its own runs.
   `mde` is a score fraction (0.08 = 8 points); when it is null, `reason`
   says what is missing instead of guessing a number. */
export interface Resolution {
  mde: number | null;
  runs_used: number;
  tests: number;
  reason: string | null;
}

export interface SuiteDoc {
  _id: string;
  name: string;
  /* What it measures. The list shows this and nothing else. */
  description?: string | null;
  provider?: string;
  model: string;
  evaluator: string;
  concurrency?: number;
  samples?: number;
  baseline_run_id?: string | null;
  created_at?: string;
  created_by?: string;
  /* The list endpoint sends a count instead of the test bodies. */
  test_count?: number;
  resolution?: Resolution;
  tests?: unknown[];
}

export interface RunDoc {
  _id: string;
  suite_id: string;
  model: string;
  status: string;
  progress: number;
  total_tests: number;
  completed_tests: number;
  created_at?: string;
  error?: string | null;
  /* Computed server-side by `run_row`, so every run list agrees. */
  passed?: number;
  scored_tests?: number;
  errors?: number;
  pass_rate?: number | null;
  rate_limited_samples?: number;
  total_cost_usd?: number;
}

export interface RunStatus {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  completed_tests: number;
  total_tests: number;
  error: string | null;
  queue_position?: number | null;
}

export const listSuites = () => authed<SuiteDoc[]>("/suites");

export const getSuite = (id: string) => authed<SuiteDoc>(`/suites/${id}`);

export const importSuite = (suite: unknown) =>
  authed<{ id: string }>("/suites/import", {
    method: "POST",
    body: JSON.stringify(suite),
  });

/** Optional overrides for a run. Omit everything for the suite's own
 *  defaults. `provider_key` is the caller's key — sent to the job, never
 *  stored. */
export interface RunOptions {
  model?: string;
  provider?: string;
  provider_key?: string;
}

export const startRun = (suiteId: string, opts: RunOptions = {}) =>
  authed<{ run_id: string; test_count: number }>(`/suites/${suiteId}/run`, {
    method: "POST",
    body: JSON.stringify(opts),
  });

/* ── workspace ── */

export interface RecentRun {
  _id: string;
  suite_id: string;
  model: string;
  provider?: string;
  evaluator?: string;
  status: string;
  created_at?: string;
  finished_at?: string;
  total_tests: number;
  completed_tests: number;
  error?: string | null;
  used_server_key?: boolean;
  passed: number;
  scored_tests: number;
  pass_rate: number | null;
  total_cost_usd: number;
}

/** My recent runs across every benchmark, newest first. */
export const listRecentRuns = (limit = 20) =>
  authed<RecentRun[]>(`/runs?limit=${limit}`);

export interface Quota {
  cap: number | null;
  used: number;
  remaining: number | null;
}

/** Runs left today on EvalBench's own key. null cap = uncapped (admin). */
export const getQuota = () => authed<Quota>("/suites/quota");

export interface Benchmark {
  slug: string;
  title: string;
  description: string;
  name: string;
  test_count: number;
  provider: string;
  model: string;
  categories: string[];
}

export const listBenchmarks = () => authed<Benchmark[]>("/suites/bundled");

/** Get my own copy of a bundled benchmark — creates one the first time,
 *  returns the same one every time after. */
export const adoptBenchmark = (slug: string) =>
  authed<{ id: string; name: string; created: boolean }>(
    `/suites/bundled/${slug}/adopt`,
    { method: "POST" }
  );

export const listModels = (provider: string) =>
  authed<{ provider: string; models: string[] }>(
    `/suites/models?provider=${encodeURIComponent(provider)}`
  );

export const listRuns = (suiteId: string) =>
  authed<RunDoc[]>(`/suites/${suiteId}/runs`);

export const getRunStatus = (id: string) =>
  authed<RunStatus>(`/runs/${id}/status`);

export const getRunSummary = (id: string) =>
  authed<RunSummary>(`/runs/${id}/summary`);

export const getRun = (id: string) =>
  authed<{ results: TestResult[] }>(`/runs/${id}`);

export const setBaseline = (suiteId: string, runId: string) =>
  authed<{ baseline_run_id: string }>(`/suites/${suiteId}/baseline`, {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });

/** Shape of POST /regression. Verified against the live endpoint —
 *  every field here is present in its response. */
export interface PerTestDelta {
  test_name: string;
  baseline_score: number | null;
  current_score: number | null;
  delta: number | null;
  regressed: boolean;
}

export interface Comparison {
  mean_diff: number;
  p_value: number | null;
  effect_size: number | null;
  significant: boolean;
  regression_detected: boolean | null;
  min_samples_for_5pt_mde: number | null;
  test_count: number;
  per_test: PerTestDelta[];
  mcnemar: {
    regressions: number;
    fixes: number;
    discordant: number;
    p_value: number;
  } | null;
}

export const compareRuns = (baselineId: string, currentId: string) =>
  authed<Comparison>("/regression", {
    method: "POST",
    body: JSON.stringify({
      baseline_run_id: baselineId,
      current_run_id: currentId,
    }),
  });

/* ── admin ── */

export interface AdminUser {
  _id: string;
  username: string;
  role: string;
  active: boolean;
  created_at?: string;
}

export interface AdminStats {
  users: number;
  suites: number;
  runs: number;
  runs_by_status: Record<string, number>;
  total_cost_usd: number;
  as_of: string;
}

export const adminUsers = () =>
  authed<{ users: AdminUser[]; count: number }>("/admin/users");

export const adminStats = () => authed<AdminStats>("/admin/stats");

export const adminSetActive = (username: string, active: boolean) =>
  authed<{ username: string; active: boolean }>(
    `/admin/users/${username}/${active ? "activate" : "deactivate"}`,
    { method: "POST" }
  );
