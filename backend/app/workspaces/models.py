from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class WorkspaceFolder(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workspace_folders"
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    external_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    uniform_access_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_synced")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("uq_workspace_folders_source_external", WorkspaceFolder.source_id, WorkspaceFolder.external_folder_id, unique=True)


class WorkspaceFolderSelection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One Google Drive root contributing to a logical workspace.

    ``external_folder_id`` is deliberately empty for virtual roots. Keeping it
    non-null makes the uniqueness constraint portable between PostgreSQL and
    SQLite, whose NULL uniqueness semantics differ.
    """

    __tablename__ = "workspace_folder_selections"
    workspace_folder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_folder_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        CheckConstraint(
            "(kind = 'folder' AND external_folder_id <> '') "
            "OR (kind IN ('root_files', 'all_accessible') AND external_folder_id = '')",
            name="ck_workspace_folder_selection_kind",
        ),
    )


Index(
    "uq_workspace_folder_selection_kind_external",
    WorkspaceFolderSelection.workspace_folder_id,
    WorkspaceFolderSelection.kind,
    WorkspaceFolderSelection.external_folder_id,
    unique=True,
)
