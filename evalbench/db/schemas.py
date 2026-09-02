from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from evalbench.core.assertions import Assertion


class TestCase(BaseModel):

    __test__ = False

    model_config = ConfigDict(populate_by_name=True)

    name: str

    prompt: str

    expected: str = ""

    threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0
    )

    # Per-test override of the suite-level evaluator (exact | contains |
    # semantic | judge | security). Falls back to the suite evaluator.
    evaluator: str | None = None

    # Composable assertions (YAML key: ``assert``). When present these are
    # used instead of the evaluator/expected/threshold triple.
    assert_: list[Assertion] | None = Field(default=None, alias="assert")

    # Optional tagging for per-category reporting.
    category: str | None = None
    difficulty: str | None = None


class TestSuite(BaseModel):

    __test__ = False

    name: str

    # Backend that serves `model` (ollama | ...). See evalbench.core.providers.
    provider: str = "ollama"

    model: str = "llama3.1"

    evaluator: str = "exact"

    # Sampling temperature passed to the model for every test.
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Number of times each test is run; the result is aggregated
    # (mean score, majority-vote pass) across the samples.
    samples: int = Field(default=1, ge=1, le=20)

    # How many tests run at once. Capped further by the provider's own
    # concurrency limit (free hosted tiers have low request-rate ceilings).
    concurrency: int = Field(default=4, ge=1, le=64)

    # Run the LLM judge / security classifier on a different backend than
    # the model under test. Both default to the suite provider (and a
    # provider-appropriate judge model) when left unset.
    judge_provider: str | None = None
    judge_model: str | None = None

    # Run id promoted as this suite's regression baseline. `evalbench run
    # --compare-to-baseline` checks the fresh run against it.
    baseline_run_id: str | None = None

    tests: list[TestCase]


class TestResult(BaseModel):

    __test__ = False

    test_name: str

    prompt: str

    expected: str

    actual: str

    latency_ms: float

    tokens: int

    # Token split + estimated USD cost (0.0 for local/free models).
    prompt_tokens: int = 0

    completion_tokens: int = 0

    cost_usd: float = 0.0

    error: str | None = None

    passed: bool | None = None

    score: float | None = None

    timestamp: datetime

    # ── Aggregation / tagging metadata (added in scoring v2) ──
    evaluator: str | None = None

    category: str | None = None

    difficulty: str | None = None

    # How many samples actually produced a score for this test.
    runs: int = 1

    # How many of those samples passed.
    pass_count: int = 0

    # Population std-dev of the sample scores (0.0 for a single sample).
    score_std: float | None = None

    # Per-assertion breakdown from the last sample:
    # [{"type", "passed", "score", "detail"}].
    assertions: list[dict] = []


class TestRun(BaseModel):

    __test__ = False

    suite_id: str

    model: str

    evaluator: str

    results: list[TestResult] = []

    created_at: datetime

    # ── Job lifecycle (async execution) ──
    # queued -> running -> completed | failed
    status: str = "completed"

    progress: float = Field(default=0.0, ge=0.0, le=1.0)

    total_tests: int = 0

    completed_tests: int = 0

    started_at: datetime | None = None

    finished_at: datetime | None = None

    error: str | None = None


class User(BaseModel):

    username: str

    hashed_password: str

    api_key: str | None = None

    role: str = "user"  # admin | user

    created_at: datetime
