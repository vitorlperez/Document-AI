from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import false as sql_false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

TRIGGER_KINDS = ("schedule", "folder_changed")
TEMPLATES = ("summary", "table", "alert")
RUN_STATUSES = ("queued", "running", "ok", "empty", "quota", "error")


class Automation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A recurring question over a set of folders; it always runs with its creator's permissions."""

    __tablename__ = "automations"
    __table_args__ = (
        CheckConstraint("trigger_kind IN ('schedule', 'folder_changed')", name="ck_automations_trigger_kind"),
        CheckConstraint("template IN ('summary', 'table', 'alert')", name="ck_automations_template"),
        Index("ix_automations_org_created", "organization_id", "created_at"),
        Index("ix_automations_due", "enabled", "trigger_kind", "next_run_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_false())
    trigger_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    scope: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)  # {"workspace_folder_ids": [...]}
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    template: Mapped[str] = mapped_column(String(20), nullable=False, default="summary")
    output_formats: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)  # user ids (strings)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("automation_id", "trigger_ref", name="uq_automation_runs_trigger_ref"),
        CheckConstraint("status IN ('queued', 'running', 'ok', 'empty', 'quota', 'error')", name="ck_automation_runs_status"),
        Index("ix_automation_runs_automation_created", "automation_id", "created_at"),
    )

    automation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")
    trigger_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    questions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(40))
