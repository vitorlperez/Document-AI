"""Identity, opaque-session and AuthKit integration boundaries."""

import base64
import json
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from workos import WorkOSClient
from workos._errors import APIError, WorkOSError

from app.identity.models import AuthIdentity, User, UserSession


class AuthenticationUnavailable(RuntimeError):
    pass


class AuthenticationRejected(RuntimeError):
    pass


class AuthenticationRateLimited(AuthenticationUnavailable):
    def __init__(self, message: str = "Muitas tentativas. Aguarde e tente novamente.", *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = max(1, math.ceil(retry_after)) if retry_after is not None and math.isfinite(retry_after) else 60


@dataclass(frozen=True)
class PendingEmailVerification:
    token: str
    verification_id: str | None = None


@dataclass(frozen=True)
class HostedAuthenticationRequired:
    """Let AuthKit handle enterprise policies, MFA and other advanced challenges."""



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
        return self._verified_identity(response)

    @staticmethod
    def _verified_identity(response) -> VerifiedIdentity:
        user = response.user
        if user is None or not user.id or not user.email or not user.email_verified:
            raise AuthenticationUnavailable("provider did not return a verified identity")
        return VerifiedIdentity(
            provider="workos",
            subject=user.id,
            email=user.email,
            provider_session_id=workos_session_id(getattr(response, "access_token", None)),
        )

    def _authenticate(self, operation, **kwargs):
        try:
            return self._verified_identity(operation(**kwargs))
        except APIError as error:
            body = error.response_json or {}
            code = body.get("code") or body.get("error")
            token = body.get("pending_authentication_token")
            if error.status_code == 429:
                raise AuthenticationRateLimited(retry_after=getattr(error, "retry_after", None)) from None
            if (error.status_code or 0) >= 500:
                raise AuthenticationUnavailable("authentication provider is unavailable") from None
            # A failed credential/code remains an error even if the provider
            # repeats a pending token. Only challenges can use hosted fallback.
            if code in {"invalid_credentials", "invalid_grant", "email_verification_code_invalid"}:
                raise AuthenticationRejected("Não foi possível autenticar. Confira os dados e tente novamente.") from None
            if code == "email_verification_required" and isinstance(token, str) and token:
                return PendingEmailVerification(token=token, verification_id=body.get("email_verification_id"))
            if code in {
                "mfa_challenge", "mfa_enrollment", "sso_required",
                "organization_selection_required", "organization_authentication_methods_required",
                "authentication_method_not_allowed", "email_password_auth_disabled",
                "radar_challenge", "radar_sign_up_challenge", "radar_email_challenge", "radar_sms_challenge",
                "passkey_progressive_enrollment",
            } or (400 <= (error.status_code or 0) < 500 and isinstance(token, str) and token and code != "email_verification_required"):
                return HostedAuthenticationRequired()
            raise AuthenticationRejected("Não foi possível autenticar. Confira os dados e tente novamente.") from None
        except WorkOSError:
            raise AuthenticationUnavailable("authentication provider is unavailable") from None

    def authenticate_password(self, *, email: str, password: str, ip_address: str | None, user_agent: str | None):
        return self._authenticate(
            self._client().user_management.authenticate_with_password,
            email=canonical_email(email), password=password, ip_address=ip_address, user_agent=user_agent,
        )

    def register_account(self, *, email: str, ip_address: str | None, user_agent: str | None) -> None:
        """Never install a password until its owner follows the emailed reset link.

        Existing users get the same ownership flow without overwriting credentials.
        confirm_password_reset both sets the password and verifies the mailbox.
        """
        email = canonical_email(email)
        resource = self._client().user_management
        try:
            if not resource.list_users(email=email, limit=1).data:
                try:
                    resource.create_user(email=email, ip_address=ip_address, user_agent=user_agent)
                except APIError as error:
                    # Resolve a concurrent signup by reading the canonical user,
                    # not by guessing the undocumented duplicate-email error code.
                    if error.status_code not in {400, 409, 422} or not resource.list_users(email=email, limit=1).data:
                        raise
        except APIError as error:
            if error.status_code == 429:
                raise AuthenticationRateLimited(retry_after=getattr(error, "retry_after", None)) from None
            if (error.status_code or 0) >= 500 or error.status_code in {401, 403}:
                raise AuthenticationUnavailable("authentication provider is unavailable") from None
            # Never reveal whether an address already has an account.
            raise AuthenticationRejected("Não foi possível iniciar o cadastro. Tente novamente ou entre na sua conta.") from None
        except WorkOSError:
            raise AuthenticationUnavailable("authentication provider is unavailable") from None
        self.request_password_reset(email=email)

    def verify_email(self, *, token: str, code: str, ip_address: str | None, user_agent: str | None):
        return self._authenticate(
            self._client().user_management.authenticate_with_email_verification,
            pending_authentication_token=token, code=code, ip_address=ip_address, user_agent=user_agent,
        )

    def resend_verification(self, *, verification_id: str) -> None:
        try:
            resource = self._client().user_management
            verification = resource.get_email_verification(verification_id)
            resource.send_verification_email(verification.user_id)
        except APIError as error:
            if error.status_code == 429:
                raise AuthenticationRateLimited(retry_after=getattr(error, "retry_after", None)) from None
            if error.status_code in {400, 404, 422}:
                raise AuthenticationRejected("A confirmação expirou. Entre novamente para receber um novo código.") from None
            raise AuthenticationUnavailable("authentication provider is unavailable") from None
        except WorkOSError:
            raise AuthenticationUnavailable("authentication provider is unavailable") from None

    def request_password_reset(self, *, email: str) -> None:
        try:
            self._client().user_management.reset_password(email=canonical_email(email))
        except APIError as error:
            if error.status_code == 404:
                return
            if error.status_code == 429:
                raise AuthenticationRateLimited(retry_after=getattr(error, "retry_after", None)) from None
            raise AuthenticationUnavailable("authentication provider is unavailable") from None
        except WorkOSError:
            raise AuthenticationUnavailable("authentication provider is unavailable") from None

    def confirm_password_reset(self, *, token: str, password: str) -> str:
        try:
            response = self._client().user_management.confirm_password_reset(token=token, new_password=password)
            return response.user.id
        except APIError as error:
            if error.status_code == 429:
                raise AuthenticationRateLimited(retry_after=getattr(error, "retry_after", None)) from None
            if (error.status_code or 0) >= 500:
                raise AuthenticationUnavailable("authentication provider is unavailable") from None
            raise AuthenticationRejected("Este link expirou ou a senha não atende aos requisitos. Solicite outro link ou revise a senha.") from None
        except WorkOSError:
            raise AuthenticationUnavailable("authentication provider is unavailable") from None

    def revoke_provider_session(self, *, session_id: str) -> None:
        try:
            self._client().user_management.revoke_session(session_id=session_id)
        except Exception as error:
            raise AuthenticationUnavailable("authentication provider is unavailable") from error



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
