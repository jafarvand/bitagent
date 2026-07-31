import httpx

from app.config import settings


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    async def generate(self, prompt: str) -> dict:
        username, password = settings.ollama_credentials()
        if not settings.bitagent_chat_enabled:
            raise OllamaError("Chat is disabled by configuration")
        if not username or not password:
            raise OllamaError("Ollama Basic Auth is not configured")

        try:
            async with httpx.AsyncClient(
                timeout=settings.ollama_timeout_seconds,
                follow_redirects=False,
                auth=httpx.BasicAuth(username, password),
            ) as client:
                response = await client.post(
                    f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                    json={
                        "model": settings.ollama_model,
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
            "model": str(payload.get("model") or settings.ollama_model),
            "done": bool(payload.get("done", True)),
            "prompt_tokens": payload.get("prompt_eval_count"),
            "response_tokens": payload.get("eval_count"),
        }


ollama_client = OllamaClient()
