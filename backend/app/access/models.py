"""Programmatic-access records: API keys, per-organization switches and the call audit trail."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

SCOPE_SEARCH = "search:read"
SCOPE_DOCUMENTS = "documents:read"
SCOPE_ASK = "ask:run"
ALL_SCOPES = frozenset({SCOPE_SEARCH, SCOPE_DOCUMENTS, SCOPE_ASK})


class ApiKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "api_keys"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Public identifier ("arq_" + 8 hex). The secret is only ever stored as a SHA-256 digest.
    prefix: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Library node ids (folders/files) the key is confined to; None = whole organization.
    node_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationAccessSettings(CreatedAtMixin, Base):
    """Fail-closed switches an Owner/Admin flips per organization."""

    __tablename__ = "organization_access_settings"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    public_api_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slack_replies_in_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ApiAuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One row per programmatic call. Never stores question text, excerpts or document text."""

    __tablename__ = "api_audit_events"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # api_key | mcp | slack | teams
    credential_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | denied | rate_limited | error
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


Index("ix_api_audit_events_org_created", ApiAuditEvent.organization_id, ApiAuditEvent.created_at)
Index("ix_api_audit_events_credential", ApiAuditEvent.credential_id, ApiAuditEvent.created_at)


class McpConnection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Binds a member's MCP identity (WorkOS subject) to exactly one organization at a time."""

    __tablename__ = "mcp_connections"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Library node ids (folders/files) the connection is confined to; None = whole organization.
    node_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "uq_mcp_connections_active_user",
    McpConnection.user_id,
    unique=True,
    postgresql_where=McpConnection.revoked_at.is_(None),
    sqlite_where=McpConnection.revoked_at.is_(None),
)
