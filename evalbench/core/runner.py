from datetime import datetime
from typing import List

from fastapi import HTTPException

from evalbench.core.models import OllamaClient
from evalbench.core.evaluators import get_evaluator
from evalbench.db.schemas import TestResult, TestRun, TestSuite


class TestRunner:
    def __init__(self):
        self.ollama = OllamaClient()

    async def validate_model(self, model: str):
        if not await self.ollama.has_model(model):
            available = await self.ollama.list_models()
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' not found in Ollama. Available: {available}",
            )

    async def run_suite(self, suite: TestSuite, suite_id: str) -> TestRun:
        await self.validate_model(suite.model)
        evaluator = get_evaluator(suite.evaluator)
        results: List[TestResult] = []

        for test in suite.tests:
            try:
                ollama_resp = await self.ollama.generate(
                    model=suite.model,
                    prompt=test.prompt,
                )
                response_text = ollama_resp.get("response", "").strip()
                latency_ms = ollama_resp.get("total_duration", 0) / 1_000_000
                tokens = ollama_resp.get("eval_count", 0)
                error = None
            except Exception as e:
                response_text = ""
                latency_ms = 0
                tokens = 0
                error = str(e)

            passed, score = await evaluator.evaluate(test.expected, response_text, test.prompt)

            results.append(
                TestResult(
                    test_name=test.name,
                    prompt=test.prompt,
                    expected=test.expected,
                    actual=response_text,
                    latency_ms=round(latency_ms, 2),
                    tokens=tokens,
                    error=error,
                    passed=passed,
                    score=round(score, 4),
                    timestamp=datetime.utcnow(),
                )
            )

        return TestRun(
            suite_id=suite_id,
            model=suite.model,
            evaluator=suite.evaluator,
            results=results,
            created_at=datetime.utcnow(),
        )

    async def close(self):
        await self.ollama.close()