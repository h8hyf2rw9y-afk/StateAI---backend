from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central app configuration, read from environment variables (and .env in
    local dev). See .env.example for every variable this app needs and
    where to find each value — nothing here should ever have a real secret
    as its default.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres connection string for SQLAlchemy/Alembic (from Supabase's
    # dashboard "Connect" button). Distinct from anything the frontend uses.
    database_url: str

    # Supabase project URL — used to build the JWKS endpoint for verifying
    # Supabase Auth JWTs. Same value as the frontend's NEXT_PUBLIC_SUPABASE_URL.
    supabase_url: str

    # The "aud" claim every valid Supabase Auth access token carries.
    supabase_jwt_aud: str = "authenticated"

    # Comma-separated list of origins allowed to call this API (CORS).
    frontend_origins: str = "http://localhost:3000"

    # Which LLMProvider app/ai/llm/factory.py builds — see app/ai/llm/base.py
    # for the abstraction both branches implement. "ollama" (the default) is
    # the local-development choice: no API key, no network egress, nothing
    # to pay for. "anthropic" is the production option, gated on
    # anthropic_api_key below. This is process-startup configuration, not a
    # CRM domain field, so it's validated here directly rather than through
    # app/schemas/enums.py's soft-enum convention (that one's for API/DB
    # fields a client can submit).
    llm_provider: Literal["ollama", "anthropic"] = "ollama"

    # Local Ollama server (https://ollama.com) — see app/ai/llm/ollama_provider.py.
    # Irrelevant unless llm_provider="ollama".
    ollama_base_url: str = "http://localhost:11434"

    # Not hardcoded anywhere else in the app — every call site reads this.
    # Must already be pulled locally (`ollama pull <model>`) before use.
    ollama_model: str = "llama3.1"

    # The Lead Intelligence Agent's production LLM provider — see
    # app/ai/llm/anthropic_provider.py. `None` (the default) means Anthropic
    # is unconfigured: only a problem if llm_provider="anthropic", in which
    # case the route returns 503 rather than a raw provider error. Never
    # given a real default value here; only ever set via the environment
    # (see .env.example).
    anthropic_api_key: str | None = None

    # Not hardcoded anywhere else in the app — every call site reads this.
    # Anthropic's current models change over time; update this one value
    # (or the environment variable) rather than a model string embedded in
    # application code.
    anthropic_model: str = "claude-sonnet-5"

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
