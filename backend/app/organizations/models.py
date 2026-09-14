import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Organization(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)


class Membership(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "memberships"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role", values_callable=lambda values: [value.value for value in values]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MembershipInvitation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "membership_invitations"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role", values_callable=lambda values: [value.value for value in values]),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformStaff(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A global platform operator, deliberately separate from tenant membership."""

    __tablename__ = "platform_staff"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffAccessGrant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An expiring metadata-only support grant for exactly one tenant."""

    __tablename__ = "staff_access_grants"

    platform_staff_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform_staff.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    granted_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


Index(
    "uq_memberships_active_org_user",
    Membership.organization_id,
    Membership.user_id,
    unique=True,
    postgresql_where=Membership.is_active.is_(True),
)

Index(
    "ix_staff_access_grants_staff_org_active",
    StaffAccessGrant.platform_staff_id,
    StaffAccessGrant.organization_id,
    StaffAccessGrant.expires_at,
    StaffAccessGrant.revoked_at,
)

Index(
    "uq_membership_invitations_pending_org_email",
    MembershipInvitation.organization_id,
    MembershipInvitation.email,
    unique=True,
    postgresql_where=(MembershipInvitation.accepted_at.is_(None) & MembershipInvitation.revoked_at.is_(None)),
)
