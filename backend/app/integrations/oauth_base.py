"""Shared, provider-neutral half of every OAuth connection service."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import UserSession
from app.integrations.models import DataSource, OAuthConnectionState
from app.organizations.models import Membership, MembershipRole


class OAuthConnectionServiceBase:
    provider: str
    access_denied: type[Exception] = PermissionError
    invalid: type[Exception] = ValueError
    retain_identity_on_disconnect = False
    state_ttl = timedelta(minutes=10)

    def __init__(self, session: Session, cipher) -> None:
        self.session, self.cipher = session, cipher

    def require_admin(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        member = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
                Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
            )
        )
        if member is None:
            raise self.access_denied("integration access denied")

    def _new_state(
        self,
        *,
        scope: OrganizationScope,
        user_id: UUID,
        session_secret: str,
        source_id: UUID | None = None,
    ) -> str:
        raw = secrets.token_urlsafe(32)
        self.session.add(
            OAuthConnectionState(
                organization_id=scope.organization_id,
                user_id=user_id,
                source_id=source_id,
                session_hash=hash_secret(session_secret),
                state_hash=hash_secret(raw),
                expires_at=datetime.now(UTC) + self.state_ttl,
            )
        )
        self.session.flush()
        return raw

    def _find_valid_state(self, *, raw_state: str, session_secret: str) -> OAuthConnectionState:
        state = self.session.scalar(
            select(OAuthConnectionState)
            .where(
                OAuthConnectionState.state_hash == hash_secret(raw_state),
                OAuthConnectionState.consumed_at.is_(None),
                OAuthConnectionState.expires_at > datetime.now(UTC),
            )
            .with_for_update()  # two parallel callbacks must not both consume one state
        )
        active_session = (
            self.session.scalar(
                select(UserSession).where(
                    UserSession.secret_hash == hash_secret(session_secret),
                    UserSession.user_id == state.user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > datetime.now(UTC),
                )
            )
            if state
            else None
        )
        if (
            state is None
            or state.session_hash != hash_secret(session_secret)
            or active_session is None
        ):
            raise self.invalid("OAuth state is invalid")
        return state

    def _consume_state(self, *, raw_state: str, session_secret: str) -> OAuthConnectionState:
        state = self._find_valid_state(raw_state=raw_state, session_secret=session_secret)
        self.require_admin(scope=OrganizationScope(state.organization_id), user_id=state.user_id)
        return state

    def _own_source(self, *, organization_id: UUID, source_id: UUID) -> DataSource | None:
        return self.session.scalar(
            select(DataSource).where(
                DataSource.id == source_id,
                DataSource.organization_id == organization_id,
                DataSource.provider == self.provider,
            )
        )

    def _on_disconnect(self, source: DataSource) -> None:  # hook
        return None

    def disconnect(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID) -> DataSource:
        self.require_admin(scope=scope, user_id=user_id)
        source = self._own_source(organization_id=scope.organization_id, source_id=source_id)
        if source is None:
            raise self.access_denied("source access denied")
        source.encrypted_credentials = None
        source.status = "disconnected"
        if not self.retain_identity_on_disconnect:
            source.account_email = None
        self.session.execute(
            update(OAuthConnectionState)
            .where(
                OAuthConnectionState.source_id == source.id,
                OAuthConnectionState.consumed_at.is_(None),
            )
            .values(consumed_at=datetime.now(UTC))
        )
        self._on_disconnect(source)
        self.session.add(
            AuditLog(
                organization_id=scope.organization_id,
                actor_user_id=user_id,
                action="data_source.disconnected",
                target_type="data_source",
                target_id=source.id,
            )
        )
        self.session.flush()
        return source
