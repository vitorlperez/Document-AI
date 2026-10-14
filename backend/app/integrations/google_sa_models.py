"""Dedicated, never recycled robots and explicit tenant folder grants."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class GoogleSaProject(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "google_sa_projects"
    gcp_project_id: Mapped[str] = mapped_column(String(255), unique=True)
    sa_quota: Mapped[int] = mapped_column(Integer, default=100)
    # Serializes IAM creations (3/min/project): written under the project row lock.
    last_iam_create_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoogleSaIdentity(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "google_sa_identities"
    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("google_sa_projects.id", ondelete="RESTRICT")
    )
    sa_email: Mapped[str] = mapped_column(String(320), unique=True)
    encrypted_key: Mapped[str | None] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="free")
    # RESTRICT preserves assignment history even when an organization is deleted.
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), unique=True
    )
    group_email: Mapped[str | None] = mapped_column(String(320))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('free','assigned','retired','compromised')",
            name="ck_google_sa_identity_status",
        ),
        CheckConstraint(
            "(status = 'free' AND organization_id IS NULL AND assigned_at IS NULL) OR (status <> 'free' AND organization_id IS NOT NULL)",
            name="ck_google_sa_identity_assignment",
        ),
    )


class DriveFolderLink(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "drive_folder_links"
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    workspace_folder_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspace_folders.id", ondelete="SET NULL")
    )
    external_folder_id: Mapped[str] = mapped_column(String(128), index=True)
    folder_name: Mapped[str] = mapped_column(String(512))
    is_shared_drive: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="verified")
    verified_via: Mapped[str] = mapped_column(String(32), default="visible_to_org_robot")
    shared_by_email: Mapped[str | None] = mapped_column(String(320))
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_download_count: Mapped[int] = mapped_column(Integer, default=0)
    suspect_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(40))
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_folder_id", name="uq_drive_folder_links_org_folder"
        ),
        CheckConstraint(
            "status IN ('pending','verified','suspect','access_lost','purge_scheduled','removed')",
            name="ck_drive_folder_link_status",
        ),
        CheckConstraint(
            "verified_via = 'visible_to_org_robot'", name="ck_drive_folder_link_explicit_share"
        ),
    )
