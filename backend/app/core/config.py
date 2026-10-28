import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with no permissive production defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
    # Swagger/ReDoc/openapi.json cover every route, private ones included. None = on outside production, off in production;
    # set API_DOCS_ENABLED explicitly to override. The public /v1/openapi.json is always served.
    api_docs_enabled: bool | None = None
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

    # Single source for the per-organization caps (spikes/library-scale/FINDINGS.md A1/A2, M8).
    # processed_bytes keeps the old 4 MB/doc headroom (2 GB / 500 docs) at 3,000 docs; embedding_tokens is x10.
    active_document_limit: int = Field(default=3_000, gt=0)
    monthly_limit_processed_bytes: int = Field(default=12_000_000_000, gt=0)
    monthly_limit_embedding_tokens: int = Field(default=10_000_000, gt=0)
    monthly_limit_questions: int = Field(default=1_000, gt=0)
    monthly_limit_ocr_pages: int = Field(default=2_000, gt=0)
    # Account types / billing (ADR-0022). The payment provider is optional: "none" means no checkout is available.
    billing_provider: str = "none"
    trial_days: int = Field(default=14, ge=1)
    # Stripe adapter (ADR-0023), read only when BILLING_PROVIDER=stripe. Prefer a restricted key (rk_) in production.
    stripe_api_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_version: str = "2026-09-30.endive"
    stripe_checkout_integration_id: str = "arquivio_checkout_pnsxiqba"
    # Customer Portal configuration (bpc_...) created by scripts/stripe_sync_catalog.py; None uses the account default.
    stripe_portal_configuration_id: str | None = None
    # Pix Automático mandate options on Checkout (requires Pix enabled in the Dashboard; see ADR-0023).
    stripe_pix_enabled: bool = False
    past_due_grace_days: int = Field(default=7, ge=0)
    account_downgrade_cooldown_days: int = Field(default=30, ge=0)
    service_name: str = "document-intelligence-api"
    auth_session_cookie_name: str = "document_intelligence_session"
    auth_login_state_cookie_name: str = "document_intelligence_login_state"
    auth_session_ttl_hours: int = 168
    auth_proxy_secret: SecretStr | None = None
    auth_trusted_proxy_cidrs: str = ""

    @field_validator("auth_proxy_secret")
    @classmethod
    def validate_auth_proxy_secret(cls, value):
        if value is not None and len(value.get_secret_value().strip()) < 32:
            raise ValueError("AUTH_PROXY_SECRET must contain at least 32 characters")
        return value

    @field_validator("auth_trusted_proxy_cidrs")
    @classmethod
    def validate_auth_proxy_cidrs(cls, value):
        from ipaddress import ip_network
        for item in value.split(","):
            if item.strip():
                try:
                    network = ip_network(item.strip())
                except ValueError:
                    raise ValueError("AUTH_TRUSTED_PROXY_CIDRS must contain valid CIDRs") from None
                if network.prefixlen == 0:
                    raise ValueError("AUTH_TRUSTED_PROXY_CIDRS must trust only frontend peers, never /0")
        return value

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.environment.strip().lower() != "production"

    @model_validator(mode="after")
    def validate_stripe(self):
        # Messages name variables only: a key value must never reach a log or an error page.
        if self.billing_provider.strip().lower() != "stripe":
            return self
        required = {"STRIPE_API_KEY": self.stripe_api_key, "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret}
        missing = [name for name, value in required.items() if not value or not value.get_secret_value().strip()]
        if missing:
            raise ValueError(f"BILLING_PROVIDER=stripe requires {' and '.join(missing)}")
        if self.environment.strip().lower() == "production":
            api_key = self.stripe_api_key.get_secret_value().strip()
            if "_test_" in api_key:
                raise ValueError("Production refuses a Stripe test-mode STRIPE_API_KEY")
            if api_key.startswith("sk_"):
                logging.getLogger("document_intelligence.config").warning(
                    "STRIPE_API_KEY is an unrestricted secret key; prefer a restricted key (rk_) in production")
        return self

    @model_validator(mode="after")
    def validate_production_auth_proxy(self):
        if self.environment.strip().lower() == "production":
            missing = []
            if not self.auth_proxy_secret:
                missing.append("AUTH_PROXY_SECRET")
            if not any(item.strip() for item in self.auth_trusted_proxy_cidrs.split(",")):
                missing.append("AUTH_TRUSTED_PROXY_CIDRS")
            if missing:
                raise ValueError(f"Production requires valid {' and '.join(missing)} before startup")
        return self

    workos_api_key: SecretStr | None = None
    workos_client_id: str | None = None
    workos_redirect_uri: str | None = None
    resend_api_key: SecretStr | None = None
    invitation_from_email: str | None = None
    public_app_url: str = "http://localhost:3000"
    google_drive_sa_enabled: bool = False
    google_sa_allowed_orgs: str = ""
    google_sa_key_encryption_key: SecretStr | None = None
    google_sa_key_encryption_previous_keys: SecretStr | None = None
    google_sa_download_workers: int = Field(default=3, ge=1, le=3)
    # On-demand robots (one per organization, never recycled). Pool projects are non-secret ids;
    # the provisioner credential (base64 service-account JSON) belongs to Worker/Beat only.
    google_sa_pool_projects: str = ""
    google_sa_project_quota: int = Field(default=100, ge=1, le=100)
    google_sa_warm_pool_size: int = Field(default=0, ge=0, le=20)
    google_sa_capacity_alert_below: int = Field(default=10, ge=0)
    google_sa_provisioner_key_b64: SecretStr | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_token_encryption_key: SecretStr | None = None
    notion_oauth_client_id: str | None = None
    notion_oauth_client_secret: SecretStr | None = None
    notion_oauth_redirect_uri: str | None = None
    notion_token_encryption_key: SecretStr | None = None
    notion_token_encryption_legacy_fallback: bool = True
    clickup_oauth_client_id: str | None = None
    clickup_oauth_client_secret: SecretStr | None = None
    clickup_oauth_redirect_uri: str | None = None
    clickup_token_encryption_key: SecretStr | None = None
    # Closed tasks are history, not working knowledge: off by default to bound embedding cost.
    clickup_include_closed_tasks: bool = False
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

    @property
    def google_sa_pool_project_list(self) -> list[str]:
        return [value.strip() for value in self.google_sa_pool_projects.split(",") if value.strip()]

    def google_sa_enabled_for(self, organization_id) -> bool:
        allowed = {value.strip() for value in self.google_sa_allowed_orgs.split(",") if value.strip()}
        return self.google_drive_sa_enabled and (not allowed or str(organization_id) in allowed)

    @model_validator(mode="after")
    def validate_sa_key(self):
        if self.google_drive_sa_enabled and not self.google_sa_key_encryption_key:
            raise ValueError("GOOGLE_SA_KEY_ENCRYPTION_KEY is required when robot Drive is enabled")
        if self.google_sa_key_encryption_key:
            from cryptography.fernet import Fernet
            Fernet(self.google_sa_key_encryption_key.get_secret_value().encode())
            if any(self.google_sa_key_encryption_key == key for key in (
                self.google_token_encryption_key, self.microsoft_token_encryption_key,
                self.notion_token_encryption_key, self.clickup_token_encryption_key)):
                raise ValueError("robot Drive requires a dedicated encryption key")
        return self

    def cipher_keys(self, provider: str) -> list[str | None]:
        key = {"google_drive_sa": self.google_sa_key_encryption_key, "google_drive": self.google_token_encryption_key,
               "onedrive": self.microsoft_token_encryption_key,
               "sharepoint": self.microsoft_token_encryption_key,
               "notion": self.notion_token_encryption_key,
               "clickup": self.clickup_token_encryption_key}[provider]
        keys = [key.get_secret_value() if key else None]
        if provider == "notion" and self.notion_token_encryption_legacy_fallback:
            keys.append(self.google_token_encryption_key.get_secret_value() if self.google_token_encryption_key else None)
        return keys

    @model_validator(mode="after")
    def validate_provider_keys(self):
        if self.environment == "production":
            keys = [self.cipher_keys(provider)[0] for provider in ("google_drive", "google_drive_sa", "onedrive", "notion", "clickup")]
            populated = [key for key in keys if key]
            if len(set(populated)) != len(populated):
                raise ValueError("each provider requires a distinct encryption key")
            if self.notion_oauth_client_id and not self.notion_token_encryption_key:
                raise ValueError("Notion requires its own encryption key in production")
            if self.clickup_oauth_client_id and not self.clickup_token_encryption_key:
                raise ValueError("ClickUp requires its own encryption key in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
