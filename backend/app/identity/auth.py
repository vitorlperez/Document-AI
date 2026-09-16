"""Identity, opaque-session and AuthKit integration boundaries."""

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from workos import WorkOSClient

from app.identity.models import AuthIdentity, User, UserSession


class AuthenticationUnavailable(RuntimeError):
    pass


def canonical_email(email: str) -> str:
    return email.strip().lower()


def hash_secret(raw_secret: str) -> str:
    return sha256(raw_secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str
    subject: str
    email: str
    provider_session_id: str | None = None


def workos_session_id(access_token: str | None) -> str | None:
    """Extract only the non-secret AuthKit session identifier from a JWT payload."""
    if not access_token:
        return None
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    session_id = claims.get("sid") if isinstance(claims, dict) else None
    return session_id if isinstance(session_id, str) and session_id.startswith("session_") else None


class WorkOSAuthKitGateway:
    """Small adapter so domain tests never need a WorkOS account or network."""

    def __init__(self, *, api_key: str | None, client_id: str | None, redirect_uri: str | None):
        self.api_key = api_key
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    def _client(self) -> WorkOSClient:
        if not self.api_key or not self.client_id or not self.redirect_uri:
            raise AuthenticationUnavailable("authentication provider is not configured")
        return WorkOSClient(api_key=self.api_key, client_id=self.client_id)

    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
        return self._client().user_management.get_authorization_url(
            provider="authkit", redirect_uri=self.redirect_uri, state=state, screen_hint=screen_hint, max_age=max_age
        )

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        response = self._client().user_management.authenticate_with_code(code=code)
        user = response.user
        if user is None or not user.id or not user.email or not user.email_verified:
            raise AuthenticationUnavailable("provider did not return a verified identity")
        return VerifiedIdentity(
            provider="workos",
            subject=user.id,
            email=user.email,
            provider_session_id=workos_session_id(getattr(response, "access_token", None)),
        )

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        return self._client().user_management.get_logout_url(session_id=session_id, return_to=return_to)


class IdentityService:
    def __init__(self, session: Session):
        self.session = session

    def establish_identity(self, identity: VerifiedIdentity) -> User:
        email = canonical_email(identity.email)
        existing = self.session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == identity.provider,
                AuthIdentity.provider_subject == identity.subject,
            )
        )
        if existing is not None:
            user = self.session.get(User, existing.user_id)
            if user is None:
                raise AuthenticationUnavailable("identity has no user")
            return user

        # A verified e-mail is profile data, not an account-linking key. Only
        # the stable provider subject can attach an external identity to a user.
        user = User(email=email)
        self.session.add(user)
        self.session.flush()
        self.session.add(
            AuthIdentity(
                user_id=user.id,
                provider=identity.provider,
                provider_subject=identity.subject,
                verified_email=email,
            )
        )
        self.session.flush()
        return user

    def create_session(self, *, user_id, ttl_hours: int, provider_session_id: str | None = None) -> tuple[UserSession, str]:
        raw_secret = secrets.token_urlsafe(32)
        session = UserSession(
            user_id=user_id,
            secret_hash=hash_secret(raw_secret),
            provider_session_id=provider_session_id,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
        self.session.add(session)
        self.session.flush()
        return session, raw_secret

    def authenticated_user(self, raw_secret: str | None) -> User | None:
        if not raw_secret:
            return None
        now = datetime.now(UTC)
        current = self.session.scalar(
            select(UserSession).where(
                UserSession.secret_hash == hash_secret(raw_secret),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )
        return self.session.get(User, current.user_id) if current else None

    def revoke_session(self, raw_secret: str | None) -> str | None:
        if not raw_secret:
            return None
        current = self.session.scalar(
            select(UserSession).where(
                UserSession.secret_hash == hash_secret(raw_secret), UserSession.revoked_at.is_(None)
            )
        )
        if current is None:
            return None
        current.revoked_at = datetime.now(UTC)
        self.session.flush()
        return current.provider_session_id

    def revoke_user_sessions(self, *, user_id) -> None:
        self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        self.session.flush()
