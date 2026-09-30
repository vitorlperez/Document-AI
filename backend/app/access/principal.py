"""Turn a presented credential into the (organization, member, scopes) the services enforce."""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.access.keys import split_api_key
from app.access.models import ApiKey, OrganizationAccessSettings
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.organizations.models import Membership, MembershipRole

_DUMMY_HASH = hash_secret("dummy-secret-for-constant-time")
_LAST_USED_GRANULARITY = timedelta(minutes=5)


class InvalidCredential(Exception):
    """Unknown, wrong, revoked, expired, disabled or orphaned credential — indistinguishable."""


class InsufficientScope(Exception):
    def __init__(self, needed: str):
        super().__init__(needed)
        self.needed = needed


@dataclass(frozen=True)
class Principal:
    organization_id: UUID
    user_id: UUID
    channel: str
    scopes: frozenset[str]
    node_ids: tuple[UUID, ...] | None = None
    credential_id: UUID | None = None
    rate_limit_per_minute: int = 60

    @property
    def scope(self) -> OrganizationScope:
        return OrganizationScope(self.organization_id)

    def require(self, needed: str) -> None:
        if needed not in self.scopes:
            raise InsufficientScope(needed)


class ApiKeyAuthenticator:
    def __init__(self, session: Session):
        self.session = session

    def authenticate(self, raw: str | None) -> Principal:
        parsed = split_api_key(raw or "")
        if parsed is None:
            raise InvalidCredential
        prefix, secret = parsed
        now = datetime.now(UTC)
        key = self.session.scalar(
            select(ApiKey).where(
                ApiKey.prefix == prefix,
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
        )
        expected = key.secret_hash if key is not None else _DUMMY_HASH
        if not hmac.compare_digest(hash_secret(secret), expected) or key is None:
            raise InvalidCredential
        settings = self.session.get(OrganizationAccessSettings, key.organization_id)
        if settings is None or not settings.public_api_enabled:
            raise InvalidCredential
        principal = Principal(
            organization_id=key.organization_id, user_id=key.created_by_user_id, channel="api_key",
            scopes=frozenset(key.scopes), credential_id=key.id,
            node_ids=tuple(UUID(item) for item in key.node_ids) if key.node_ids else None,
            rate_limit_per_minute=key.rate_limit_per_minute,
        )
        member = self.session.scalar(select(Membership).where(
            Membership.organization_id == principal.organization_id,
            Membership.user_id == principal.user_id,
            Membership.is_active.is_(True),
            Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
        ))
        if member is None:
            raise InvalidCredential
        if key.last_used_at is None or now - _aware(key.last_used_at) > _LAST_USED_GRANULARITY:
            key.last_used_at = now
        return principal


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
