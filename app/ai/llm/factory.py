"""
The one place that decides which LLMProvider the app actually uses today —
switched via settings.llm_provider (env var LLM_PROVIDER, default
"ollama"). Swapping the active provider means changing an environment
variable, not the agent, the route, or this function's callers.
"""

from app.ai.llm.anthropic_provider import AnthropicProvider
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError
from app.ai.llm.ollama_provider import OllamaProvider
from app.core.config import settings


def build_default_provider() -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url, model=settings.ollama_model, timeout=settings.ollama_timeout_seconds
        )

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY is not configured. Set it in your environment "
                "(see .env.example) to use LLM_PROVIDER=anthropic."
            )
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    # Unreachable while llm_provider stays a Literal["ollama", "anthropic"]
    # in app/core/config.py — kept as a defensive, honest failure rather
    # than silently falling back to some default if that type ever widens.
    raise LLMConfigError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'.")
