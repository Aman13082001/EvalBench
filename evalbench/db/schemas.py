from pydantic import BaseModel, Field

from typing import List

from datetime import datetime


class TestCase(BaseModel):

    name: str

    prompt: str

    expected: str

    threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0
    )

    # Per-test override of the suite-level evaluator (exact | contains |
    # semantic | judge | security). Falls back to the suite evaluator.
    evaluator: str | None = None

    # Optional tagging for per-category reporting.
    category: str | None = None
    difficulty: str | None = None


class TestSuite(BaseModel):

    name: str

    model: str = "llama3.1"

    evaluator: str = "exact"

    # Sampling temperature passed to the model for every test.
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Number of times each test is run; the result is aggregated
    # (mean score, majority-vote pass) across the samples.
    samples: int = Field(default=1, ge=1, le=20)

    tests: List[TestCase]


class TestResult(BaseModel):

    __test__ = False

    test_name: str

    prompt: str

    expected: str

    actual: str

    latency_ms: float

    tokens: int

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


class TestRun(BaseModel):

    __test__ = False

    suite_id: str

    model: str

    evaluator: str

    results: list[TestResult]

    created_at: datetime


class User(BaseModel):

    username: str

    hashed_password: str

    api_key: str | None = None

    role: str = "user"  # admin | user

    created_at: datetime
