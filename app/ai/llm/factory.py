"""
The one place that decides which LLMProvider the app actually uses today.
Swapping providers (or making it user/org-configurable later) means
changing this function's body — never the agent, never the route.
"""

from app.ai.llm.anthropic_provider import AnthropicProvider
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError
from app.core.config import settings


def build_default_provider() -> LLMProvider:
    if not settings.anthropic_api_key:
        raise LLMConfigError(
            "ANTHROPIC_API_KEY is not configured. Set it in your environment "
            "(see .env.example) to enable the Lead Intelligence Agent."
        )
    return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
