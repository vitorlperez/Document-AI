"""Isolated real API for browser QA; only AuthKit, Drive and worker dispatch are fake.

From backend/: PYTHONPATH=. .venv/bin/python ../artifacts/onboarding/qa-server.py
Frontend: VITE_API_BASE_URL=http://localhost:8011 npm run dev
No production configuration or data is used; SQLite state lives in this process only.
"""
import os
import tempfile
from urllib.parse import urlencode
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"

import uvicorn
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import VerifiedIdentity
from app.main import create_app
from tests.api.test_auth_and_invitations import FakeInvitationDelivery
from tests.api.test_google_integrations import FakeGooglePort

QA_API_PORT = int(os.environ.get("QA_API_PORT", "8011"))
QA_API_URL = f"http://localhost:{QA_API_PORT}"
QA_APP_URL = os.environ.get("QA_APP_URL", "http://localhost:5173")


class AuthGateway:
    def authorization_url(self, *, state, screen_hint=None, max_age=None):
        if screen_hint == "sign-up" or not hasattr(self, "subject"):
            self.subject = str(uuid4())
        return f"{QA_API_URL}/auth/callback?" + urlencode({"state": state, "code": self.subject})

    def exchange_code(self, *, code):
        return VerifiedIdentity(provider="workos", subject=code, email=f"qa-{code}@example.com")


class GooglePort(FakeGooglePort):
    def authorization_url(self, *, state, scope):
        return f"{QA_API_URL}/data-sources/google/oauth/callback?" + urlencode({"state": state, "code": "qa"})


class Dispatcher:
    def dispatch(self, *, job_id):
        pass  # Real durable queue rows are asserted; no external ingestion here.


app = create_app(Settings(
    database_url=os.environ["DATABASE_URL"], environment="development",
    public_app_url=QA_APP_URL, google_token_encryption_key=Fernet.generate_key().decode(),
))
# Each request gets its own connection, including concurrent library loads.
# A shared StaticPool connection can roll back another request's transaction.
qa_directory = tempfile.TemporaryDirectory(prefix="document-ai-onboarding-")
engine = create_engine(f"sqlite:///{qa_directory.name}/qa.db", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
app.state.auth_gateway = AuthGateway()
app.state.google_drive_port = GooglePort()
app.state.ingestion_dispatcher = Dispatcher()
app.state.invitation_delivery = FakeInvitationDelivery()


@app.get("/qa/invitations")
def delivered_invitations():
    """Test-only outbox: this isolated QA server never sends real email."""
    return app.state.invitation_delivery.messages

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=QA_API_PORT, log_level="warning")
