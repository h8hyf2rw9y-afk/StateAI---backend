"""
app/ai/llm/factory.py's provider selection (settings.llm_provider), and
confirmation that the Anthropic implementation added before Ollama is
still intact and usable — none of this touches a network.
"""

import pytest

from app.ai.llm.anthropic_provider import AnthropicProvider
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError
from app.ai.llm.factory import build_default_provider
from app.ai.llm.ollama_provider import OllamaProvider
from app.core.config import settings


def test_default_provider_is_ollama_and_needs_no_anthropic_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    provider = build_default_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider.provider_name == "ollama"


def test_ollama_provider_uses_the_configured_base_url_and_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:9999")
    monkeypatch.setattr(settings, "ollama_model", "some-other-model")

    provider = build_default_provider()

    assert provider.model_name == "some-other-model"


def test_ollama_provider_uses_the_configured_timeout_not_the_class_default(monkeypatch):
    """
    Regression test: build_default_provider() must pass settings.ollama_timeout_seconds
    through — OllamaProvider's own class default (60s) is far too short for
    real CPU-only inference (measured at 2-3+ minutes per call), and was
    silently causing every real request to fail with LLMTimeoutError before
    this was wired up.
    """
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_timeout_seconds", 180.0)

    provider = build_default_provider()

    assert provider.timeout == 180.0


def test_anthropic_provider_selected_without_a_key_raises_llm_config_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    with pytest.raises(LLMConfigError):
        build_default_provider()


def test_anthropic_provider_selected_with_a_key_is_returned(monkeypatch):
    """
    Confirms the Anthropic implementation from the previous phase still
    works end to end through the factory — it is not required for local
    development (Ollama is the default), but it must remain fully
    functional for when LLM_PROVIDER=anthropic is chosen.
    """
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-fake-for-this-test")
    monkeypatch.setattr(settings, "anthropic_model", "claude-sonnet-5")

    provider = build_default_provider()

    assert isinstance(provider, AnthropicProvider)
    assert provider.provider_name == "anthropic"
    assert provider.model_name == "claude-sonnet-5"


def test_both_providers_implement_the_same_llm_provider_interface():
    anthropic = AnthropicProvider(api_key="sk-ant-fake", model="claude-sonnet-5")
    ollama = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")

    assert isinstance(anthropic, LLMProvider)
    assert isinstance(ollama, LLMProvider)
