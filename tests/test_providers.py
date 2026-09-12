"""Provider abstraction: registry, presets, and adapters."""

from unittest.mock import AsyncMock, patch

import pytest

from evalbench.core.providers import (
    MockProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
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

    def test_available_providers_lists_classes_and_presets(self):
        avail = available_providers()
        assert {"ollama", "mock", "groq", "gemini", "github"} <= set(avail)


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_returns_configured_response(self):
        p = get_provider("mock")
        assert isinstance(p, MockProvider)
        r = await p.generate("any", "hi")
        assert r.text == "mock response"
        assert r.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_kwargs_passthrough(self):
        p = get_provider("mock", response="42", completion_tokens=1)
        r = await p.generate("m", "q")
        assert r.text == "42"
        assert r.completion_tokens == 1


class TestPresets:
    def test_preset_builds_openai_compatible_with_env_key(self, monkeypatch):
        # Isolate from any real key in the developer's .env.
        monkeypatch.setattr(
            "evalbench.core.providers.settings.groq_api_key", "", raising=False
        )
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        p = get_provider("groq")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.name == "groq"
        assert p.base_url == "https://api.groq.com/openai/v1"
        assert p._client.headers["authorization"] == "Bearer gsk_test"

    def test_preset_without_key_raises_with_env_var_name(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr(
            "evalbench.core.providers.settings.groq_api_key", "", raising=False
        )
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            get_provider("groq")

    def test_explicit_api_key_override(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = get_provider("gemini", api_key="AIza_x")
        assert isinstance(p, OpenAICompatibleProvider)
        assert "generativelanguage.googleapis.com" in p.base_url

    def test_base_url_override(self, monkeypatch):
        p = get_provider(
            "openrouter", api_key="k", base_url="http://localhost:9999/v1"
        )
        assert p.base_url == "http://localhost:9999/v1"

    def test_presets_carry_free_tier_concurrency_caps(self):
        assert get_provider("groq", api_key="k").max_concurrency == 4
        assert get_provider("github", api_key="k").max_concurrency == 1
        assert get_provider("gemini", api_key="k").max_concurrency == 2
        assert get_provider("openai", api_key="k").max_concurrency == 8


class TestConcurrencyDefaults:
    def test_class_provider_concurrency(self):
        assert get_provider("ollama").max_concurrency == 8
        assert get_provider("mock").max_concurrency == 64


class TestOpenAICompatibleProvider:
    @pytest.mark.asyncio
    async def test_generate_maps_chat_completion(self):
        fake = {
            "model": "llama-3.3-70b-versatile",
            "choices": [
                {
                    "message": {"content": "Paris"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 2},
        }
        p = OpenAICompatibleProvider(
            base_url="https://api.groq.com/openai/v1",
            api_key="k",
            name="groq",
        )
        with patch.object(
            p._client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value.json = lambda: fake
            mock_post.return_value.raise_for_status = lambda: None

            r = await p.generate("llama-3.3-70b-versatile", "capital of France?")

        assert isinstance(r, LLMResponse)
        assert r.text == "Paris"
        assert r.prompt_tokens == 11
        assert r.completion_tokens == 2
        assert r.finish_reason == "stop"
        assert r.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_list_models_swallows_errors(self):
        p = OpenAICompatibleProvider(base_url="http://x/v1", api_key="k")
        with patch.object(
            p._client, "get", new_callable=AsyncMock, side_effect=Exception("no /models")
        ):
            assert await p.list_models() == []

    @pytest.mark.asyncio
    async def test_retries_429_then_succeeds(self):
        p = OpenAICompatibleProvider(
            base_url="https://api.groq.com/openai/v1", api_key="k", name="groq"
        )

        def _resp(status, body=None):
            m = type("R", (), {})()
            m.status_code = status
            m.headers = {}
            m.json = lambda: body or {}
            m.raise_for_status = lambda: None
            return m

        ok = _resp(200, {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
        with (
            patch.object(
                p._client, "post", new_callable=AsyncMock,
                side_effect=[_resp(429), _resp(429), ok],
            ),
            patch("evalbench.core.providers.openai_compat.asyncio.sleep",
                  new_callable=AsyncMock),
        ):
            r = await p.generate("m", "q")
        assert r.text == "hi"

    @pytest.mark.asyncio
    async def test_persistent_429_raises_rate_limit_error(self):
        from evalbench.core.providers.base import RateLimitError

        p = OpenAICompatibleProvider(
            base_url="https://api.groq.com/openai/v1", api_key="k", name="groq"
        )
        m = type("R", (), {})()
        m.status_code = 429
        m.headers = {}
        with (
            patch.object(
                p._client, "post", new_callable=AsyncMock, return_value=m
            ),
            patch("evalbench.core.providers.openai_compat.asyncio.sleep",
                  new_callable=AsyncMock),
        ):
            with pytest.raises(RateLimitError, match="rate limited"):
                await p.generate("m", "q")


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


class TestChatModelFilter:
    """Provider model lists include speech, audio and classifier models.
    Tried every one Groq listed: Whisper and Orpheus return 400 to a chat
    request, prompt-guard answers with a probability. Suggesting them as
    models to evaluate is a trap; a caller can still type any name."""

    @pytest.mark.parametrize(
        "name",
        [
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "canopylabs/orpheus-v1-english",
            "meta-llama/llama-prompt-guard-2-22m",
            "text-embedding-3-small",
            "playai-tts",
        ],
    )
    def test_non_chat_models_are_hidden(self, name):
        from evalbench.core.providers import is_chat_model

        assert not is_chat_model(name)

    @pytest.mark.parametrize(
        "name",
        [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "llama3.1",
            "qwen/qwen3.8-27b",
            "gemini-2.0-flash",
            "gpt-4o-mini",
            "allam-2-7b",
        ],
    )
    def test_chat_models_are_kept(self, name):
        from evalbench.core.providers import is_chat_model

        assert is_chat_model(name)

    def test_models_endpoint_splits_them(self, client, mock_db):
        from unittest.mock import AsyncMock, MagicMock, patch

        fake = MagicMock()
        fake.list_models = AsyncMock(
            return_value=["openai/gpt-oss-20b", "whisper-large-v3"]
        )
        fake.close = AsyncMock()
        with patch("evalbench.api.routes.get_provider", return_value=fake):
            body = client.get("/suites/models?provider=groq").json()
        assert body["models"] == ["openai/gpt-oss-20b"]
        assert body["hidden"] == ["whisper-large-v3"]
