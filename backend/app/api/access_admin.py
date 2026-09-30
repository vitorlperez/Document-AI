"""Cookie-authenticated Owner/Admin management of programmatic access."""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.keys import generate_api_key
from app.access.models import ALL_SCOPES, ApiKey, OrganizationAccessSettings
from app.api.auth import current_user, database_session
from app.audit_usage.models import AuditLog
from app.identity.models import User
from app.library.models import LibraryNode
from app.organizations.models import Membership, MembershipRole

router = APIRouter(prefix="/organizations/{organization_id}", tags=["access-administration"])


class KeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=3)
    node_ids: list[UUID] | None = Field(default=None, max_length=20)
    expires_at: datetime | None = None
    rate_limit_per_minute: int = Field(default=60, ge=1, le=600)

    @field_validator("scopes")
    @classmethod
    def known_scopes(cls, value):
        if not set(value) <= ALL_SCOPES:
            raise ValueError("unknown scope")
        return sorted(set(value))

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(UTC)):
            raise ValueError("expiry must be a future timestamp with timezone")
        return value


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_api_enabled: bool


def _require_admin(session: Session, organization_id: UUID, user_id: UUID):
    member = session.scalar(select(Membership).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id,
        Membership.is_active.is_(True), Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
    ))
    if member is None:
        raise HTTPException(403, "owner or admin required")


def _audit(session, org, user_id, action, target_type, target_id):
    session.add(AuditLog(organization_id=org, actor_user_id=user_id, action=action,
                         target_type=target_type, target_id=target_id))


def _serialize(key: ApiKey):
    return {"id": str(key.id), "name": key.name, "prefix": key.prefix, "scopes": key.scopes,
            "node_ids": key.node_ids, "expires_at": key.expires_at, "last_used_at": key.last_used_at,
            "revoked_at": key.revoked_at, "rate_limit_per_minute": key.rate_limit_per_minute}


@router.post("/api-keys", status_code=201)
def create_key(organization_id: UUID, payload: KeyInput,
               user: User = Depends(current_user), session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    node_ids = list(dict.fromkeys(payload.node_ids or []))
    if node_ids:
        found = set(session.scalars(select(LibraryNode.id).where(
            LibraryNode.organization_id == organization_id, LibraryNode.id.in_(node_ids),
            LibraryNode.kind.in_(["folder", "file"]),
        )))
        if found != set(node_ids):
            raise HTTPException(422, "node unavailable")
    generated = generate_api_key()
    key = ApiKey(organization_id=organization_id, created_by_user_id=user.id,
                 name=payload.name, prefix=generated.prefix, secret_hash=generated.secret_hash,
                 scopes=payload.scopes, node_ids=[str(node) for node in node_ids] or None,
                 expires_at=payload.expires_at, rate_limit_per_minute=payload.rate_limit_per_minute)
    session.add(key)
    session.flush()
    _audit(session, organization_id, user.id, "api_key.created", "api_key", key.id)
    return _serialize(key) | {"key": generated.raw}


@router.get("/api-keys")
def list_keys(organization_id: UUID, user: User = Depends(current_user),
              session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    return [_serialize(key) for key in session.scalars(select(ApiKey).where(
        ApiKey.organization_id == organization_id).order_by(ApiKey.created_at.desc()))]


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(organization_id: UUID, key_id: UUID, user: User = Depends(current_user),
               session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    key = session.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id))
    if key is None:
        raise HTTPException(404, "not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        _audit(session, organization_id, user.id, "api_key.revoked", "api_key", key.id)
    return Response(status_code=204)


@router.get("/access-settings")
def get_access_settings(organization_id: UUID, user: User = Depends(current_user),
                        session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    row = session.get(OrganizationAccessSettings, organization_id)
    return {"public_api_enabled": bool(row and row.public_api_enabled), "mcp_enabled": bool(row and row.mcp_enabled)}


@router.put("/access-settings")
def update_access_settings(organization_id: UUID, payload: SettingsInput,
                           user: User = Depends(current_user), session: Session = Depends(database_session)):
    _require_admin(session, organization_id, user.id)
    row = session.get(OrganizationAccessSettings, organization_id)
    if row is None:
        row = OrganizationAccessSettings(organization_id=organization_id)
        session.add(row)
    row.public_api_enabled = payload.public_api_enabled
    session.flush()
    _audit(session, organization_id, user.id, "access_settings.updated", "access_settings", organization_id)
    return {"public_api_enabled": row.public_api_enabled, "mcp_enabled": row.mcp_enabled}
