from functools import lru_cache

from pydantic import PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with no permissive production defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn

    @field_validator("database_url", mode="before")
    @classmethod
    def use_installed_postgres_driver(cls, value: str) -> str:
        # Railway's Postgres template exports postgresql://, while this image
        # installs psycopg 3 instead of SQLAlchemy's default psycopg2 driver.
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        if isinstance(value, str) and value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value
    environment: str = "development"
    service_name: str = "document-intelligence-api"
    auth_session_cookie_name: str = "document_intelligence_session"
    auth_login_state_cookie_name: str = "document_intelligence_login_state"
    auth_session_ttl_hours: int = 168
    workos_api_key: SecretStr | None = None
    workos_client_id: str | None = None
    workos_redirect_uri: str | None = None
    resend_api_key: SecretStr | None = None
    invitation_from_email: str | None = None
    public_app_url: str = "http://localhost:3000"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_token_encryption_key: SecretStr | None = None
    notion_oauth_client_id: str | None = None
    notion_oauth_client_secret: SecretStr | None = None
    notion_oauth_redirect_uri: str | None = None
    notion_token_encryption_key: SecretStr | None = None
    microsoft_oauth_client_id: str | None = None
    microsoft_oauth_client_secret: SecretStr | None = None
    microsoft_oauth_redirect_uri: str | None = None
    microsoft_token_encryption_key: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"
    sync_scheduler_interval_minutes: int = 15
    sync_freshness_hours: int = 24
    sync_scheduler_max_concurrent_per_org: int = 3
    sync_scheduler_failure_cooldown_minutes: int = 30
    sync_scheduler_slo_grace_hours: int = 2
    openai_api_key: SecretStr | None = None
    agent_tools_enabled: bool = False
    agent_max_steps: int = 4
    agent_max_tool_result_bytes: int = 48_000
    agent_max_seconds: int = 25
    # Small-model intent classifier -> tools -> one grounded synthesis call. Off by
    # default until measured; it only runs inside the agent (AGENT_TOOLS_ENABLED)
    # and falls back to keyword routing when the classifier fails.
    agent_planner_enabled: bool = False
    agent_planner_model: str = "gpt-5-nano"
    agent_synthesis_model: str = "gpt-5-mini"
    # Seconds the small intent classifier may take before the keyword fallback decides.
    agent_intent_timeout_seconds: float = 4.0
    # Per-file summaries in catalog answers: one batched call to a cheap model that is asked
    # for about this many characters per file (a target in the prompt, not a cut).
    agent_file_summary_chars: int = 350
    agent_file_summary_model: str = "gpt-5-nano"
    agent_file_summary_timeout_seconds: float = 8.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
