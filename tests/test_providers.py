"""Provider abstraction: registry + Ollama adapter."""

from unittest.mock import AsyncMock, patch

import pytest

from evalbench.core.providers import (
    OllamaProvider,
    available_providers,
    get_provider,
)
from evalbench.core.providers.base import LLMResponse


class TestRegistry:
    def test_get_default_provider(self):
        p = get_provider()
        assert isinstance(p, OllamaProvider)
        assert p.name == "ollama"

    def test_get_named_provider_case_insensitive(self):
        assert isinstance(get_provider("Ollama"), OllamaProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("does-not-exist")

    def test_available_providers_lists_ollama(self):
        assert "ollama" in available_providers()


class TestOllamaProvider:
    @pytest.mark.asyncio
    async def test_generate_maps_response_to_llmresponse(self):
        fake = {
            "response": "  4  ",
            "prompt_eval_count": 7,
            "eval_count": 3,
            "total_duration": 2_000_000_000,  # ns -> 2000 ms
            "done_reason": "stop",
        }
        provider = OllamaProvider(base_url="http://x:11434")
        with patch.object(
            provider._client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value.json = lambda: fake
            mock_post.return_value.raise_for_status = lambda: None

            resp = await provider.generate("llama3.1", "2+2?", temperature=0.0)

        assert isinstance(resp, LLMResponse)
        assert resp.text == "  4  "
        assert resp.prompt_tokens == 7
        assert resp.completion_tokens == 3
        assert resp.total_tokens == 10
        assert resp.latency_ms == 2000.0
        assert resp.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_has_model_matches_bare_and_tagged(self):
        provider = OllamaProvider()
        provider.list_models = AsyncMock(return_value=["llama3.1:latest", "qwen:7b"])
        assert await provider.has_model("llama3.1") is True
        assert await provider.has_model("qwen:7b") is True
        assert await provider.has_model("mistral") is False

    @pytest.mark.asyncio
    async def test_has_model_assumes_true_when_unlistable(self):
        provider = OllamaProvider()
        provider.list_models = AsyncMock(return_value=[])
        assert await provider.has_model("anything") is True
