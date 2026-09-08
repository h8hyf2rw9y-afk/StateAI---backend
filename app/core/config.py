from functools import lru_cache

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

    # The Lead Intelligence Agent's LLM provider — see app/ai/llm/. `None`
    # (the default) means the agent is unconfigured: routes return 503
    # rather than a raw provider error. Never given a real default value
    # here; only ever set via the environment (see .env.example).
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
