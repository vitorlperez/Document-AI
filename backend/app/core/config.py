from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
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
    source_fencing_enabled: bool = True
    vector_backend: Literal["python", "pgvector"] = "pgvector"
    ocr_engine: Literal["none", "docling_serve"] = "none"
    docling_serve_url: str | None = None
    docling_serve_version: str = "v1.35.0-pt1"
    docling_serve_timeout_seconds: float = Field(default=120, gt=0)
    ocr_max_pages_per_job: int = Field(default=200, ge=0)
    ocr_job_deadline_seconds: float = Field(default=1200, gt=0)
    ocr_languages: str = "por,eng"
    ocr_cloud_fallback_enabled: bool = False
    ocr_cloud_dpa_approved: bool = False

    @model_validator(mode="after")
    def validate_ocr(self):
        if self.ocr_engine == "docling_serve" and not self.docling_serve_url:
            raise ValueError("Docling requires its private endpoint")
        return self

    new_formats_enabled: bool = False
    active_document_limit: int = Field(default=500, gt=0)
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
    notion_token_encryption_legacy_fallback: bool = True
    microsoft_oauth_client_id: str | None = None
    microsoft_oauth_client_secret: SecretStr | None = None
    microsoft_oauth_redirect_uri: str | None = None
    microsoft_token_encryption_key: SecretStr | None = None
    microsoft_sharepoint_redirect_uri: str | None = None
    sharepoint_download_workers: int = Field(default=2, ge=1, le=8)
    max_file_bytes: int = Field(default=104_857_600, ge=0)  # MAX_FILE_BYTES: one cap for every provider
    sharepoint_catalog_max_sites: int = Field(default=200, ge=1)
    api_org_rate_limit_per_minute: int = Field(default=600, gt=0)
    api_ask_rate_limit_per_minute: int = Field(default=10, gt=0)
    public_api_ask_enabled: bool = False
    mcp_resource_url: str | None = None
    mcp_issuer_url: str | None = None
    mcp_jwks_url: str | None = None
    mcp_allowed_hosts: str = ""
    mcp_rate_limit_per_minute: int = Field(default=60, gt=0)
    mcp_static_key_enabled: bool = False  # plan C: accept an organization API key as the MCP Bearer
    redis_url: str = "redis://localhost:6379/0"
    sync_scheduler_interval_minutes: int = 15
    sync_freshness_hours: int = 24
    sync_scheduler_max_concurrent_per_org: int = 3
    sync_scheduler_failure_cooldown_minutes: int = 30
    sync_scheduler_slo_grace_hours: int = 2
    openai_api_key: SecretStr | None = None
    agent_tools_enabled: bool = False
    agent_max_tool_result_bytes: int = 48_000
    agent_max_seconds: int = 25
    # The agent (AGENT_TOOLS_ENABLED) is one flow: a small-model intent classifier ->
    # local tools -> one grounded synthesis call. A failed classifier falls back to a
    # relevance search over the attached scope.
    agent_planner_model: str = "gpt-5-nano"
    # Who decides the intent: "jev" (TypeSafe's decision model, called directly; returns typed
    # choices, so the retrieval question joins the conversation instead of being rewritten) or
    # "llm" (agent_planner_model). Without TYPESAFE_API_KEY the agent uses "llm" and logs it (an
    # error in production); a failing Jev call also falls back to "llm". The key is not required
    # at startup because the worker and MCP services share these settings and never classify.
    agent_intent_engine: Literal["llm", "jev"] = "jev"
    agent_jev_model: str = "jev-1.13.0"
    typesafe_api_key: SecretStr | None = None
    agent_synthesis_model: str = "gpt-5-mini"
    # Seconds the small intent classifier may take before the relevance-search fallback answers.
    agent_intent_timeout_seconds: float = 8.0
    # Per-file summaries in catalog answers: one batched call to a cheap model that is asked
    # for about this many characters per file (a target in the prompt, not a cut).
    agent_file_summary_chars: int = 350
    agent_file_summary_model: str = "gpt-5-nano"
    agent_file_summary_timeout_seconds: float = 8.0
    # Total evidence input for content answers (~16k tokens at the default).
    # Whole relevant chunks are packed by score; per-file brief length is separate.
    evidence_context_chars: int = Field(default=64_000, ge=1024)

    def cipher_keys(self, provider: str) -> list[str | None]:
        key = {"google_drive": self.google_token_encryption_key,
               "onedrive": self.microsoft_token_encryption_key,
               "sharepoint": self.microsoft_token_encryption_key,
               "notion": self.notion_token_encryption_key}[provider]
        keys = [key.get_secret_value() if key else None]
        if provider == "notion" and self.notion_token_encryption_legacy_fallback:
            keys.append(self.google_token_encryption_key.get_secret_value() if self.google_token_encryption_key else None)
        return keys

    @model_validator(mode="after")
    def validate_provider_keys(self):
        if self.environment == "production":
            keys = [self.cipher_keys(provider)[0] for provider in ("google_drive", "onedrive", "notion")]
            populated = [key for key in keys if key]
            if len(set(populated)) != len(populated):
                raise ValueError("each provider requires a distinct encryption key")
            if self.notion_oauth_client_id and not self.notion_token_encryption_key:
                raise ValueError("Notion requires its own encryption key in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
