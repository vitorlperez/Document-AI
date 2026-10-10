from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A message for one member of one organization; ``data`` carries citations and references only."""

    __tablename__ = "notifications"

    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_notifications_user_org_created", Notification.user_id, Notification.organization_id, Notification.created_at)


class NotificationPreference(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_notification_preferences_org_user"),)

    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
