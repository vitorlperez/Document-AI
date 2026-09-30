"""Cookie-authenticated management of the MCP switch (Owner/Admin) and each member's own binding."""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.models import McpConnection, OrganizationAccessSettings
from app.api.access_admin import _audit, _require_admin
from app.api.auth import current_user, database_session
from app.identity.models import User
from app.library.models import LibraryNode
from app.organizations.models import Membership

router = APIRouter(prefix="/organizations/{organization_id}", tags=["mcp-administration"])


class McpSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mcp_enabled: bool


class McpConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_ids: list[UUID] | None = Field(default=None, max_length=20)


def _require_member(session: Session, organization_id: UUID, user_id: UUID) -> None:
    if session.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id,
        Membership.is_active.is_(True),
    )) is None:
        raise HTTPException(403, "membership required")


def _active(session: Session, user_id: UUID) -> McpConnection | None:
    return session.scalar(select(McpConnection).where(
        McpConnection.user_id == user_id, McpConnection.revoked_at.is_(None)))


def _serialize(connection: McpConnection | None, organization_id: UUID) -> dict[str, object]:
    if connection is None or connection.organization_id != organization_id:
        return {"active": False}
    return {"active": True, "organization_id": str(connection.organization_id), "node_ids": connection.node_ids}


@router.put("/mcp-settings")
def update_mcp_settings(organization_id: UUID, payload: McpSettingsInput,
                        user: User = Depends(current_user), session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    row = session.get(OrganizationAccessSettings, organization_id)
    if row is None:
        row = OrganizationAccessSettings(organization_id=organization_id)
        session.add(row)
    row.mcp_enabled = payload.mcp_enabled
    session.flush()
    _audit(session, organization_id, user.id, "mcp_settings.updated", "access_settings", organization_id)
    return {"mcp_enabled": row.mcp_enabled}


@router.put("/mcp-connection")
def enable_connection(organization_id: UUID, payload: McpConnectionInput,
                      user: User = Depends(current_user), session: Session = Depends(database_session)):
    _require_member(session, organization_id, user.id)
    settings = session.get(OrganizationAccessSettings, organization_id)
    if settings is None or not settings.mcp_enabled:
        raise HTTPException(403, "mcp is not enabled for this organization")
    node_ids = list(dict.fromkeys(payload.node_ids or []))
    if node_ids:
        found = set(session.scalars(select(LibraryNode.id).where(
            LibraryNode.organization_id == organization_id, LibraryNode.id.in_(node_ids),
            LibraryNode.kind.in_(["folder", "file"]),
        )))
        if found != set(node_ids):
            raise HTTPException(422, "node unavailable")
    previous = _active(session, user.id)
    if previous is not None:
        previous.revoked_at = datetime.now(UTC)
        session.flush()  # release the partial unique index before inserting the replacement
    connection = McpConnection(organization_id=organization_id, user_id=user.id,
                               node_ids=[str(node) for node in node_ids] or None)
    session.add(connection)
    session.flush()
    _audit(session, organization_id, user.id, "mcp_connection.enabled", "mcp_connection", connection.id)
    return _serialize(connection, organization_id)


@router.get("/mcp-connection")
def get_connection(organization_id: UUID, user: User = Depends(current_user),
                   session: Session = Depends(database_session)):
    _require_member(session, organization_id, user.id)
    return _serialize(_active(session, user.id), organization_id)


@router.delete("/mcp-connection", status_code=204)
def revoke_connection(organization_id: UUID, user: User = Depends(current_user),
                      session: Session = Depends(database_session)):
    _require_member(session, organization_id, user.id)
    connection = _active(session, user.id)
    if connection is not None and connection.organization_id == organization_id:
        connection.revoked_at = datetime.now(UTC)
        _audit(session, organization_id, user.id, "mcp_connection.revoked", "mcp_connection", connection.id)
    return Response(status_code=204)
