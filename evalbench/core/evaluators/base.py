from abc import ABC, abstractmethod


class Evaluator(ABC):
    @abstractmethod
    async def evaluate(
        self,
        expected: str,
        actual: str,
        original_prompt: str = "",
        threshold: float | None = None,
    ) -> tuple[bool, float]:
        """Return (passed, score_between_0_and_1).

        ``threshold`` is the per-test pass cutoff from the suite YAML.
        Evaluators that produce a graded score compare against it (falling
        back to their own default when it is ``None``); binary evaluators
        may ignore it.
        """
        pass
