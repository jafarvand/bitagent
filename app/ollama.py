import httpx

from app.config import settings


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    def _auth(self) -> httpx.BasicAuth:
        username, password = settings.ollama_credentials()
        if not username or not password:
            raise OllamaError("Ollama Basic Auth is not configured")
        return httpx.BasicAuth(username, password)

    async def models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.ollama_timeout_seconds,
                follow_redirects=False,
                auth=self._auth(),
                transport=self.transport,
            ) as client:
                response = await client.get(
                    f"{settings.ollama_base_url.rstrip('/')}/api/tags"
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError("Ollama model discovery failed") from exc
        names = [
            item.get("name")
            for item in payload.get("models", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        return sorted(set(names))

    async def resolve_model(self, names: list[str] | None = None) -> str:
        configured = settings.ollama_model
        names = names if names is not None else await self.models()
        if configured in names:
            return configured
        matches = [
            name
            for name in names
            if name == f"{configured}:latest"
            or name.startswith(f"{configured}:")
            or name.startswith(configured)
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise OllamaError("Configured Ollama model is not installed")
        raise OllamaError("Configured Ollama model name is ambiguous; use an exact tag")

    async def generate(self, prompt: str) -> dict:
        if not settings.bitagent_chat_enabled:
            raise OllamaError("Chat is disabled by configuration")
        model = await self.resolve_model()

        try:
            async with httpx.AsyncClient(
                timeout=settings.ollama_timeout_seconds,
                follow_redirects=False,
                auth=self._auth(),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError("Ollama request failed") from exc

        answer = payload.get("response")
        if not isinstance(answer, str) or not answer.strip():
            raise OllamaError("Ollama returned no answer")
        return {
            "answer": answer.strip(),
            "model": str(payload.get("model") or model),
            "done": bool(payload.get("done", True)),
            "prompt_tokens": payload.get("prompt_eval_count"),
            "response_tokens": payload.get("eval_count"),
        }


ollama_client = OllamaClient()
