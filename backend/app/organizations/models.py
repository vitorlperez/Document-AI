import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


ACCOUNT_PERSONAL = "personal"
ACCOUNT_BUSINESS = "business"
ACCOUNT_TYPES = (ACCOUNT_PERSONAL, ACCOUNT_BUSINESS)


class Organization(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint("account_type IN ('personal','business')", name="ck_organizations_account_type"),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    onboarding_step: Mapped[str] = mapped_column(
        String(24), nullable=False, default="welcome", server_default="welcome"
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Account type + entitlement projection (ADR-0022). Rows predating it stay ``business``/``legacy``: the model
    # defaults are the legacy ones, organization creation through the API always passes an explicit trial plan.
    account_type: Mapped[str] = mapped_column(String(16), nullable=False, default=ACCOUNT_BUSINESS, server_default=ACCOUNT_BUSINESS)
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy", server_default="legacy")
    entitlement_source: Mapped[str] = mapped_column(String(16), nullable=False, default="legacy", server_default="legacy")
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_type_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    billing_provider: Mapped[str | None] = mapped_column(String(32))
    billing_customer_id: Mapped[str | None] = mapped_column(String(128))


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
    tour_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    space_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class PlatformStaff(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A global platform operator, deliberately separate from tenant membership."""

    __tablename__ = "platform_staff"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ``support`` is read-only; only ``admin`` may grant comps.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="support", server_default="support")


class OrganizationComp(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Local courtesy plan granted by a platform admin; wins over any subscription, trial or legacy."""

    __tablename__ = "organization_comps"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False)
    limits_override: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    granted_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))


class Subscription(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Provider-agnostic subscription mirror. Only ``BillingService.apply_event`` writes it."""

    __tablename__ = "subscriptions"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_customer_id: Mapped[str | None] = mapped_column(String(128))
    external_subscription_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False, default="month", server_default="month")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coupon_code: Mapped[str | None] = mapped_column(String(64))
    discount_summary: Mapped[dict | None] = mapped_column(JSON)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingEvent(CreatedAtMixin, Base):
    """Idempotency ledger for normalized provider events."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(190), primary_key=True)  # "<provider>:<external event id>"
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(240))


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
    "uq_organization_comps_active_org",
    OrganizationComp.organization_id,
    unique=True,
    postgresql_where=OrganizationComp.revoked_at.is_(None),
    sqlite_where=OrganizationComp.revoked_at.is_(None),
)

Index(
    "uq_subscriptions_provider_external",
    Subscription.provider,
    Subscription.external_subscription_id,
    unique=True,
)

Index(
    "uq_membership_invitations_pending_org_email",
    MembershipInvitation.organization_id,
    MembershipInvitation.email,
    unique=True,
    postgresql_where=(MembershipInvitation.accepted_at.is_(None) & MembershipInvitation.revoked_at.is_(None)),
)
