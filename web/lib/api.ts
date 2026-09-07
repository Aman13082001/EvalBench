import { authed } from "./auth";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface CategoryStat {
  total: number;
  passed: number;
  errors: number;
  pass_rate: number;
  avg_score: number;
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
  pass_rate: number;
  avg_score: number;
  pass_rate_ci: [number, number] | null;
  avg_score_ci: [number, number] | null;
  avg_latency_ms: number;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  rate_limited_samples: number;
  by_category: Record<string, CategoryStat>;
  assertion_types: Record<string, { passed: number; failed: number }>;
  results: TestResult[];
}

export interface PlaygroundInfo {
  providers: string[];
  max_tests: number;
  max_samples: number;
  assertion_types: string[];
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

export function getPlaygroundInfo(): Promise<PlaygroundInfo> {
  return fetch(`${API_URL}/playground/providers`).then((r) =>
    j<PlaygroundInfo>(r)
  );
}

export function runPlayground(
  suite: unknown,
  providerKey: string
): Promise<RunSummary> {
  return fetch(`${API_URL}/playground/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suite, provider_key: providerKey }),
  }).then((r) => j<RunSummary>(r));
}

export function getPlaygroundRun(id: string): Promise<RunSummary> {
  return fetch(`${API_URL}/playground/runs/${id}`).then((r) =>
    j<RunSummary>(r)
  );
}

/* ────────────────────────────────────────────────────────────────
   Authenticated endpoints. These mirror the API exactly — see
   `evalbench/api/routes.py`, `main.py` and `admin.py`.
   ──────────────────────────────────────────────────────────────── */


export interface SuiteDoc {
  _id: string;
  name: string;
  provider?: string;
  model: string;
  evaluator: string;
  concurrency?: number;
  samples?: number;
  baseline_run_id?: string | null;
  created_at?: string;
  created_by?: string;
  tests: unknown[];
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

export const startRun = (suiteId: string) =>
  authed<{ run_id: string; test_count: number }>(`/suites/${suiteId}/run`, {
    method: "POST",
  });

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
