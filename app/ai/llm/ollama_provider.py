"""
OllamaProvider — talks to a locally running Ollama server
(https://ollama.com) over its HTTP API. This is the default local-
development provider (app/core/config.py's `llm_provider`, default
"ollama") precisely because it needs no API key and no network egress:
everything stays on the developer's machine, so State AI can be developed
and tested without incurring any LLM API cost.

Structured output uses Ollama's native "Structured outputs" feature:
passing the requested Pydantic model's own JSON schema as the request's
`format` field constrains the model's decoding to that shape — the same
"ask for exactly this shape, not prose" intent AnthropicProvider gets via a
forced tool call, just through Ollama's own mechanism instead of tool-use.
This works with any locally installed chat model; it doesn't require a
tool-calling-capable one.
"""

import httpx
from pydantic import ValidationError

from app.ai.llm.base import LLMProvider, ResponseModelT
from app.ai.llm.errors import LLMInvalidOutputError, LLMProviderError, LLMTimeoutError


class OllamaProvider(LLMProvider):
    def __init__(self, *, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def timeout(self) -> float:
        """The configured per-request timeout, in seconds — for introspection/tests, not used by any agent."""
        return self._timeout

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[ResponseModelT], max_tokens: int = 1024
    ) -> ResponseModelT:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": response_model.model_json_schema(),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        try:
            response = httpx.post(f"{self._base_url}/api/chat", json=payload, timeout=self._timeout)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"The local Ollama server at {self._base_url} did not respond in time.") from exc
        except httpx.ConnectError as exc:
            raise LLMProviderError(
                f"Could not reach the local Ollama server at {self._base_url}. "
                "Is Ollama running? Start it (e.g. `ollama serve`, or open the Ollama app) and try again."
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LLMProviderError(
                    f"Model '{self._model}' is not available on this Ollama server. "
                    f"Pull it first with `ollama pull {self._model}`."
                ) from exc
            raise LLMProviderError(f"The Ollama server returned an error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"The Ollama server returned an error: {exc}") from exc

        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMInvalidOutputError("The Ollama server's response was not in the expected shape.") from exc

        try:
            return response_model.model_validate_json(content)
        except ValidationError as exc:
            raise LLMInvalidOutputError(f"The model's output failed schema validation: {exc}") from exc
