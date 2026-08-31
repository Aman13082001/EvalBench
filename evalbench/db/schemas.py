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


class TestSuite(BaseModel):

    name: str

    model: str = "llama3.1"

    evaluator: str = "exact"

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
