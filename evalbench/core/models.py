import httpx

from evalbench.config import settings


class OllamaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url or settings.ollama_base_url
        ).rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=settings.default_request_timeout
        )

    async def generate(self, model: str, prompt: str) -> dict:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7},
        }

        response = await self.client.post(
            f"{self.base_url}/api/generate",
            json=payload,
        )

        response.raise_for_status()
        return response.json()

    async def list_models(self) -> list[str]:
        response = await self.client.get(
            f"{self.base_url}/api/tags"
        )

        response.raise_for_status()

        data = response.json()

        return [
            model["name"]
            for model in data.get("models", [])
        ]

    async def has_model(self, model: str) -> bool:
        models = await self.list_models()

        # Ollama names may include :latest
        return any(
            name == model or name == f"{model}:latest"
            for name in models
        )

    async def close(self):
        await self.client.aclose()