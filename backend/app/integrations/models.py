from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class DataSource(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "data_sources"
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    sa_identity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("google_sa_identities.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="connected")
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connected_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_data_sources_google_sa_org", "organization_id", unique=True,
              postgresql_where=text("provider = 'google_drive_sa'"),
              sqlite_where=text("provider = 'google_drive_sa'")),
        # One SharePoint source per organization and Microsoft tenant (ADR-0016, D-A3).
        Index(
            "uq_data_sources_sharepoint_tenant",
            "organization_id",
            "provider_account_id",
            unique=True,
            postgresql_where=text("provider = 'sharepoint' AND provider_account_id IS NOT NULL"),
            sqlite_where=text("provider = 'sharepoint' AND provider_account_id IS NOT NULL"),
        ),
    )


class OAuthConnectionState(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "oauth_connection_states"
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=True)
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClickUpTaskCreation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Ledger of the human-approved ClickUp write (ADR-0020): idempotency key, outcome and ids only, never content."""

    __tablename__ = "clickup_task_creations"
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    list_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_clickup_task_creations_org_key"),
        CheckConstraint("status IN ('pending', 'created', 'failed')", name="ck_clickup_task_creations_status"),
        Index("ix_clickup_task_creations_user_created", "user_id", "created_at"),
        Index("ix_clickup_task_creations_message", "message_id"),
    )

# Register additive SA tables wherever DataSource metadata is loaded.
from app.integrations import google_sa_models  # noqa: E402, F401
