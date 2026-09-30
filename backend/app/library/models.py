"""Safe, tenant-scoped metadata used to browse integrated company content."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class LibraryNode(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "library_nodes"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("library_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


Index("uq_library_nodes_source_external", LibraryNode.source_id, LibraryNode.external_id, unique=True)
Index("ix_library_nodes_organization_parent", LibraryNode.organization_id, LibraryNode.parent_id)


class ManualSyncRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Historical snapshots survive removal of the workspace or source."""
    __tablename__ = "manual_sync_runs"

    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    scope_kind: Mapped[str] = mapped_column(String(16))
    scope_external_id: Mapped[str | None] = mapped_column(String(255))
    scope_name: Mapped[str] = mapped_column(String(512))
    triggered_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    triggered_by: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Per-workspace durable progress, including file outcomes and queue failures.
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
