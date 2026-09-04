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
