from functools import lru_cache

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with no permissive production defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
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
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
