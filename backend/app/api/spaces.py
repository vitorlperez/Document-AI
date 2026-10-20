"""Spaces administration HTTP boundary (ADR-0021). A Space the caller cannot see is a uniform 404."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.organizations.models import Membership
from app.spaces.models import SPACE_ROLES
from app.spaces.service import (
    SpaceConflict,
    SpaceDenied,
    SpaceNotFound,
    SpaceService,
    SpaceView,
)

router = APIRouter(prefix="/organizations/{organization_id}/spaces", tags=["spaces"])


class SpaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = False


class SpacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    role: str = Field(default="member")


class RoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str


class GrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disclosure: dict[str, object]


def _context(session: Session, organization_id: UUID, user: User) -> tuple[SpaceService, OrganizationScope]:
    """People outside the organization see nothing at all: 404, never 403."""
    member = session.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id, Membership.user_id == user.id,
        Membership.is_active.is_(True)))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "space not found")
    return SpaceService(session), OrganizationScope(organization_id)


def _view(item: SpaceView) -> dict[str, object]:
    return {
        "id": str(item.id), "name": item.name, "description": item.description, "is_default": item.is_default,
        "member_count": item.member_count, "folder_count": item.folder_count, "my_role": item.my_role,
    }


def _run(session: Session, action):
    try:
        result = action()
        session.commit()
        return result
    except SpaceNotFound as error:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "space not found") from error
    except SpaceDenied as error:
        session.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed") from error
    except SpaceConflict as error:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


def _one(service: SpaceService, scope: OrganizationScope, user: User, space_id: UUID) -> dict[str, object]:
    return _view(next(item for item in service.list_spaces_for_actor(scope, user.id) if item.id == space_id))


@router.get("")
def list_spaces(
    organization_id: UUID, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> list[dict[str, object]]:
    service, scope = _context(session, organization_id, user)
    return _run(session, lambda: [_view(item) for item in service.list_spaces_for_actor(scope, user.id)])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_space(
    organization_id: UUID, payload: SpaceInput, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    service, scope = _context(session, organization_id, user)

    def action():
        space = service.create_space(scope, user.id, payload.name, payload.description, payload.is_default)
        return _one(service, scope, user, space.id)

    return _run(session, action)


@router.patch("/{space_id}")
def rename_space(
    organization_id: UUID, space_id: UUID, payload: SpacePatch, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    service, scope = _context(session, organization_id, user)

    def action():
        service.rename_space(scope, user.id, space_id, payload.name, payload.description)
        return _one(service, scope, user, space_id)

    return _run(session, action)


@router.delete("/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_space(
    organization_id: UUID, space_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> Response:
    service, scope = _context(session, organization_id, user)
    _run(session, lambda: service.archive_space(scope, user.id, space_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{space_id}/members")
def list_members(
    organization_id: UUID, space_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str]]:
    service, scope = _context(session, organization_id, user)
    return _run(session, lambda: [
        {"user_id": str(item.user_id), "email": item.email, "role": item.role}
        for item in service.members(scope, user.id, space_id)
    ])


@router.post("/{space_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    organization_id: UUID, space_id: UUID, payload: MemberInput, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    service, scope = _context(session, organization_id, user)
    if payload.role not in SPACE_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid space role")
    member = _run(session, lambda: service.add_member(scope, user.id, space_id, payload.user_id, payload.role))
    return {"user_id": str(member.user_id), "role": member.role}


@router.patch("/{space_id}/members/{member_user_id}")
def change_member_role(
    organization_id: UUID, space_id: UUID, member_user_id: UUID, payload: RoleInput,
    user: User = Depends(current_user), session: Session = Depends(database_session),
) -> dict[str, str]:
    service, scope = _context(session, organization_id, user)
    member = _run(session, lambda: service.set_member_role(scope, user.id, space_id, member_user_id, payload.role))
    return {"user_id": str(member.user_id), "role": member.role}


@router.delete("/{space_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    organization_id: UUID, space_id: UUID, member_user_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> Response:
    service, scope = _context(session, organization_id, user)
    _run(session, lambda: service.remove_member(scope, user.id, space_id, member_user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{space_id}/members/{member_user_id}/impact")
def member_impact(
    organization_id: UUID, space_id: UUID, member_user_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, int]:
    service, scope = _context(session, organization_id, user)
    return _run(session, lambda: service.member_impact(scope, user.id, space_id, member_user_id))


@router.post("/{space_id}/folders/{workspace_folder_id}", status_code=status.HTTP_201_CREATED)
def grant_folder(
    organization_id: UUID, space_id: UUID, workspace_folder_id: UUID, payload: GrantInput,
    user: User = Depends(current_user), session: Session = Depends(database_session),
) -> dict[str, str]:
    service, scope = _context(session, organization_id, user)
    grant = _run(session, lambda: service.grant_folder(
        scope, user.id, space_id, workspace_folder_id, payload.disclosure))
    return {"space_id": str(grant.space_id), "workspace_folder_id": str(grant.workspace_folder_id)}


@router.delete("/{space_id}/folders/{workspace_folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_folder(
    organization_id: UUID, space_id: UUID, workspace_folder_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> Response:
    service, scope = _context(session, organization_id, user)
    _run(session, lambda: service.revoke_folder(scope, user.id, space_id, workspace_folder_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{space_id}/enter")
def enter_space(
    organization_id: UUID, space_id: UUID, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    service, scope = _context(session, organization_id, user)
    member = _run(session, lambda: service.enter_space(scope, user.id, space_id))
    return {"space_id": str(member.space_id), "role": member.role}
