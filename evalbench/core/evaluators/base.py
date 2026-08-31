from abc import ABC, abstractmethod


class Evaluator(ABC):
    @abstractmethod
    async def evaluate(self, expected: str, actual: str, original_prompt: str = "") -> tuple[bool, float]:
        """Return (passed, score_between_0_and_1)"""
        pass
