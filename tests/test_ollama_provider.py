"""
OllamaProvider (app/ai/llm/ollama_provider.py) in isolation. Every test
here monkeypatches httpx.post to a canned fake response/exception — no real
Ollama server is required or contacted, except
test_connect_error_against_a_real_closed_port, which deliberately dials a
real local port nothing is listening on (instant ECONNREFUSED, no network
egress, no Ollama install needed) to prove the "Ollama unavailable" path
end-to-end rather than only through a mock.
"""

import httpx
import pytest
from pydantic import BaseModel

from app.ai.llm.errors import LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.llm.ollama_provider import OllamaProvider


class _Analysis(BaseModel):
    priority: str
    confidence: float


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, json_body: dict | None = None):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("POST", "http://x"), response=self)  # type: ignore[arg-type]

    def json(self):
        return self._json_body


def _provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://localhost:11434", model="llama3.1")


def test_generate_structured_returns_a_validated_model(monkeypatch):
    fake = _FakeResponse(json_body={"message": {"content": '{"priority": "high", "confidence": 0.9}'}})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: fake)

    result = _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)

    assert result == _Analysis(priority="high", confidence=0.9)


def test_sends_the_response_schema_as_the_format_field(monkeypatch):
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(json_body={"message": {"content": '{"priority": "low", "confidence": 0.1}'}})

    monkeypatch.setattr(httpx, "post", fake_post)

    _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["format"] == _Analysis.model_json_schema()
    assert captured["json"]["model"] == "llama3.1"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "sys"}


def test_timeout_raises_llm_timeout_error(monkeypatch):
    def raise_timeout(*a, **k):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", raise_timeout)

    with pytest.raises(LLMTimeoutError):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_connection_error_raises_a_helpful_llm_provider_error(monkeypatch):
    def raise_connect_error(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", raise_connect_error)

    with pytest.raises(LLMProviderError, match="Is Ollama running"):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_model_not_found_raises_a_helpful_llm_provider_error(monkeypatch):
    fake = _FakeResponse(status_code=404, json_body={"error": "model not found"})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: fake)

    with pytest.raises(LLMProviderError, match="ollama pull"):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_malformed_response_shape_raises_llm_invalid_output_error(monkeypatch):
    fake = _FakeResponse(json_body={"unexpected": "shape"})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: fake)

    with pytest.raises(LLMInvalidOutputError):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_content_that_fails_schema_validation_raises_llm_invalid_output_error(monkeypatch):
    fake = _FakeResponse(json_body={"message": {"content": '{"priority": "high"}'}})  # missing required "confidence"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: fake)

    with pytest.raises(LLMInvalidOutputError):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_content_that_is_not_valid_json_raises_llm_invalid_output_error(monkeypatch):
    fake = _FakeResponse(json_body={"message": {"content": "not json at all"}})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: fake)

    with pytest.raises(LLMInvalidOutputError):
        _provider().generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)


def test_connect_error_against_a_real_closed_port():
    """
    No mocking: dials a real local port nothing listens on. Fails instantly
    (connection refused), so this stays fast and needs no Ollama install —
    it proves the "Ollama unavailable" path works against a genuine socket
    failure, not just a simulated one.
    """
    provider = OllamaProvider(base_url="http://localhost:1", model="llama3.1", timeout=5.0)

    with pytest.raises(LLMProviderError, match="Is Ollama running"):
        provider.generate_structured(system_prompt="sys", user_prompt="user", response_model=_Analysis)
