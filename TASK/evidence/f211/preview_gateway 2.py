"""LOCAL PREVIEW ONLY. SQLite + deterministic gateway; no WorkOS calls or emails."""

import os

os.environ["DATABASE_URL"] = "postgresql+psycopg://preview:dummy@localhost/preview"
os.environ["OCR_ENGINE"] = "none"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.ratelimit import InMemoryRateLimiter
from pydantic import SecretStr

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import AuthenticationRejected, HostedAuthenticationRequired, PendingEmailVerification, VerifiedIdentity
from app.main import create_app

app = create_app(Settings(database_url=os.environ["DATABASE_URL"], environment="development", public_app_url=os.getenv("PREVIEW_FRONTEND_URL", "http://localhost:3117"), workos_api_key=None, workos_client_id=None, auth_proxy_secret=SecretStr("test-only-proxy-secret-at-least-32-chars") if os.getenv("PREVIEW_SIGNED_PROXY") == "1" else None, auth_trusted_proxy_cidrs="127.0.0.1/32" if os.getenv("PREVIEW_SIGNED_PROXY") == "1" else ""))
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
app.state.rate_limiter = InMemoryRateLimiter()


class PreviewGateway:
    def authenticate_password(self, **kwargs):
        if kwargs["password"] != "preview-password":
            raise AuthenticationRejected("Use preview-password na demonstração local.")
        if kwargs["email"] == "radar@example.com":
            return HostedAuthenticationRequired()
        if kwargs["email"] == "verify@example.com":
            return PendingEmailVerification(token="preview-pending", verification_id="email_verification_preview")
        return VerifiedIdentity(provider="workos", subject="user_preview", email="demo@example.com")

    def register_account(self, **kwargs):
        return None

    def verify_email(self, **kwargs):
        if kwargs["code"] != "123456":
            raise AuthenticationRejected("Código incorreto na demonstração local.")
        return VerifiedIdentity(provider="workos", subject="user_preview", email="demo@example.com")

    def resend_verification(self, **kwargs):
        return None

    def request_password_reset(self, **kwargs):
        return None

    def confirm_password_reset(self, **kwargs):
        return "user_preview"

    def revoke_provider_session(self, **kwargs):
        return None

    def authorization_url(self, **kwargs):
        return "https://auth.example.test/preview-only"


app.state.auth_gateway = PreviewGateway()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PREVIEW_API_PORT", "8117")), proxy_headers=False, log_level="warning")
