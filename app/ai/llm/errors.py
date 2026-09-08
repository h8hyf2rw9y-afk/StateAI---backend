"""
Every failure mode an LLMProvider can raise, as a single exception family —
so callers (the agent, the route) can handle "the AI service didn't work"
without importing or catching any vendor-specific exception type.
"""


class LLMError(Exception):
    """Base class for every LLM-provider-layer failure. Never raised directly."""


class LLMConfigError(LLMError):
    """The provider is missing required configuration (e.g. no API key) — a deployment problem, not the caller's fault."""


class LLMTimeoutError(LLMError):
    """The provider did not respond within the configured timeout."""


class LLMProviderError(LLMError):
    """The provider's API itself returned an error (auth failure, rate limit, 5xx, ...)."""


class LLMInvalidOutputError(LLMError):
    """The provider responded, but its output didn't match the requested structured schema."""
