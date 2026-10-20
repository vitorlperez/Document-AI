"""Spaces: named groups of people, granted explicit sync scopes (ADR-0021). No content is copied."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

SPACE_ROLE_MEMBER = "member"
SPACE_ROLE_MANAGER = "manager"
SPACE_ROLES = (SPACE_ROLE_MEMBER, SPACE_ROLE_MANAGER)


def _org_fk() -> Mapped[UUID]:
    return mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Space(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "spaces"

    organization_id: Mapped[UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_spaces_org_name_active", Space.organization_id, Space.name_key, unique=True,
    postgresql_where=Space.archived_at.is_(None), sqlite_where=Space.archived_at.is_(None),
)
Index(
    "uq_spaces_org_default", Space.organization_id, unique=True,
    postgresql_where=Space.is_default.is_(True) & Space.archived_at.is_(None),
    sqlite_where=Space.is_default.is_(True) & Space.archived_at.is_(None),
)


class SpaceMember(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "space_members"
    __table_args__ = (CheckConstraint("role IN ('member','manager')", name="ck_space_member_role"),)

    organization_id: Mapped[UUID] = _org_fk()
    space_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=SPACE_ROLE_MEMBER)
    added_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_space_members_active", SpaceMember.space_id, SpaceMember.user_id, unique=True,
    postgresql_where=SpaceMember.removed_at.is_(None), sqlite_where=SpaceMember.removed_at.is_(None),
)
Index(
    "ix_space_members_user_active", SpaceMember.organization_id, SpaceMember.user_id,
    postgresql_where=SpaceMember.removed_at.is_(None), sqlite_where=SpaceMember.removed_at.is_(None),
)


class SpaceFolderGrant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A synchronized scope (WorkspaceFolder) belongs to a Space. Revocation is logical."""

    __tablename__ = "space_folder_grants"

    organization_id: Mapped[UUID] = _org_fk()
    space_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_folder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_folders.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    disclosure: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_space_grants_active", SpaceFolderGrant.space_id, SpaceFolderGrant.workspace_folder_id, unique=True,
    postgresql_where=SpaceFolderGrant.revoked_at.is_(None), sqlite_where=SpaceFolderGrant.revoked_at.is_(None),
)
Index(
    "ix_space_grants_folder_active", SpaceFolderGrant.workspace_folder_id,
    postgresql_where=SpaceFolderGrant.revoked_at.is_(None), sqlite_where=SpaceFolderGrant.revoked_at.is_(None),
)
