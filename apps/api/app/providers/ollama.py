import json
from time import monotonic, sleep

import httpx

MAX_RESPONSE_BYTES = 64 * 1024


class GenerationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def installed_models(url: str) -> dict[str, str]:
    try:
        with httpx.Client(base_url=url, timeout=2, trust_env=False) as client:
            response = client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
            return {model["name"]: model["digest"] for model in payload["models"]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise GenerationError(
            "provider_unavailable",
            "Ollama is unavailable or returned an invalid model list.",
            503,
        ) from None


def generation_status(settings) -> dict:
    if not settings.generation_enabled:
        return {
            "available": False,
            "reason": "Generation is disabled. Enable it after starting Ollama and pulling a model.",
            "models": [],
        }
    try:
        installed = installed_models(settings.ollama_url)
    except GenerationError as exc:
        return {"available": False, "reason": str(exc), "models": []}
    models = [
        {"name": name, "digest": installed[name]}
        for name in settings.ollama_models
        if name in installed
    ]
    return {
        "available": bool(models),
        "reason": None if models else "No configured model is installed in Ollama.",
        "models": models,
    }


def generate(settings, model: str, messages: list[dict], schema: dict) -> dict:
    """One total deadline; retry at most once on a transient 429/503 response."""
    deadline = monotonic() + settings.generation_timeout_seconds
    try:
        with httpx.Client(base_url=settings.ollama_url, trust_env=False) as client:
            for attempt in range(2):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise httpx.TimeoutException("deadline")
                with client.stream(
                    "POST",
                    "/api/chat",
                    timeout=remaining,
                    json={
                        "model": model,
                        "stream": False,
                        "messages": messages,
                        "format": schema,
                        "options": {
                            "temperature": 0,
                            "seed": 42,
                            "num_predict": settings.generation_max_tokens,
                            "num_ctx": 8192,
                            "num_thread": 4,
                        },
                        "keep_alive": "5m",
                    },
                ) as response:
                    if response.status_code in (429, 503) and attempt == 0:
                        sleep(min(0.25, max(0, deadline - monotonic())))
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    for block in response.iter_bytes():
                        if monotonic() > deadline:
                            raise httpx.TimeoutException("deadline")
                        data.extend(block)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise GenerationError(
                                "provider_response_invalid",
                                "Ollama response exceeded the output size limit.",
                            )
                    payload = json.loads(data)
                if payload.get("done") is not True or not isinstance(
                    payload.get("message", {}).get("content"), str
                ):
                    raise GenerationError(
                        "provider_response_invalid",
                        "Ollama returned an incomplete response.",
                    )
                if payload.get("done_reason") == "length":
                    raise GenerationError(
                        "output_truncated",
                        "Model output reached the token limit. Try fewer chunks or increase the configured output budget.",
                    )
                counts = {}
                for field in ("prompt_eval_count", "eval_count"):
                    count = payload.get(field)
                    counts[field] = count if type(count) is int and count >= 0 else None
                return {
                    "content": payload["message"]["content"],
                    "token_usage": counts,
                    "attempts": attempt + 1,
                }
    except httpx.TimeoutException:
        raise GenerationError(
            "provider_timeout", "Ollama generation timed out.", 504
        ) from None
    except httpx.HTTPStatusError as exc:
        status = 503 if exc.response.status_code in (404, 429, 503) else 502
        raise GenerationError(
            "provider_unavailable",
            "Ollama could not generate an answer. Check that the selected model is installed.",
            status,
        ) from None
    except httpx.RequestError:
        raise GenerationError(
            "provider_unavailable",
            "Cannot connect to the configured Ollama server.",
            503,
        ) from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GenerationError(
            "provider_response_invalid", "Ollama returned an invalid response."
        ) from None
    raise GenerationError(
        "provider_unavailable", "Ollama is temporarily unavailable.", 503
    )
