import httpx


class OllamaClient:
    def __init__(self, base_url: str = "http://host.docker.internal:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, model: str, prompt: str) -> dict:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7},
        }
        response = await self.client.post(
            f"{self.base_url}/api/generate", json=payload
        )
        response.raise_for_status()
        return response.json()

    async def list_models(self) -> list[str]:
        response = await self.client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m["name"] for m in data.get("models", [])]

    async def has_model(self, model: str) -> bool:
        models = await self.list_models()
        # Ollama names sometimes include :latest tag
        return any(m.startswith(model) for m in models)

    async def close(self):
        await self.client.aclose()