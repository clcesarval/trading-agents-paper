from typing import Any
import httpx


class OllamaProvider:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def health_check(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return {"available": True, "models": len(response.json().get("models", []))}
        except (httpx.HTTPError, ValueError) as exc:
            return {"available": False, "error": str(exc)}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])

    async def generate(self, model: str, prompt: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.base_url}/api/generate", json={"model": model, "prompt": prompt, "stream": False})
            response.raise_for_status()
            return response.json()
