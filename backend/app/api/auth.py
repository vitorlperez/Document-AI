"""HTTP boundary for AuthKit sessions and internal organization invitations."""

import secrets
from collections.abc import Generator
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.identity.auth import (
    AuthenticationUnavailable,
    IdentityService,
    VerifiedIdentity,
)
from app.identity.models import User
from app.organizations.delivery import InvitationDeliveryPort
from app.organizations.models import MembershipRole
from app.organizations.service import InvitationInvalid, InvitationNotAllowed, OrganizationService
from app.organizations.staff_access import PlatformStaffAccessService

router = APIRouter(tags=["authentication"])


def _safe_invitation_return_to(value: str | None) -> str | None:
    """Accept only an opaque invitation path; never redirect a login externally."""
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    prefix = "/invitations/"
    if not parsed.path.startswith(prefix):
        return None
    token = parsed.path.removeprefix(prefix)
    if not 20 <= len(token) <= 128 or not all(character.isalnum() or character in "_-" for character in token):
        return None
    return parsed.path


class OrganizationCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class InvitationCreateInput(BaseModel):
    email: EmailStr
    role: MembershipRole


class MembershipRoleUpdateInput(BaseModel):
    role: Literal[MembershipRole.ADMIN, MembershipRole.MEMBER]


def database_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(request: Request, session: Session = Depends(database_session)) -> User:
    settings = request.app.state.settings
    user = IdentityService(session).authenticated_user(request.cookies.get(settings.auth_session_cookie_name))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return user


@router.get("/auth/login")
def login(request: Request, return_to: str | None = None) -> RedirectResponse:
    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
    try:
        authorization_url = request.app.state.auth_gateway.authorization_url(state=state)
    except AuthenticationUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication unavailable") from error
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.auth_login_state_cookie_name,
        state,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=600,
    )
    safe_return_to = _safe_invitation_return_to(return_to)
    if safe_return_to:
        response.set_cookie(
            "document_intelligence_return_to",
            safe_return_to,
            httponly=True,
            secure=settings.environment != "development",
            samesite="lax",
            max_age=600,
        )
    else:
        response.delete_cookie("document_intelligence_return_to")
    return response


@router.get("/auth/callback")
def callback(
    request: Request, code: str, state: str | None = None, session: Session = Depends(database_session)
) -> Response:
    settings = request.app.state.settings
    expected_state = request.cookies.get(settings.auth_login_state_cookie_name)
    if state is None or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication failed")
    try:
        identity: VerifiedIdentity = request.app.state.auth_gateway.exchange_code(code=code)
    except AuthenticationUnavailable as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication failed") from error
    service = IdentityService(session)
    user = service.establish_identity(identity)
    _, raw_session = service.create_session(user_id=user.id, ttl_hours=settings.auth_session_ttl_hours)
    return_to = _safe_invitation_return_to(request.cookies.get("document_intelligence_return_to"))
    destination = f"{settings.public_app_url.rstrip('/')}{return_to}" if return_to else settings.public_app_url
    response = RedirectResponse(destination, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.auth_session_cookie_name,
        raw_session,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 60 * 60,
    )
    response.delete_cookie(settings.auth_login_state_cookie_name)
    response.delete_cookie("document_intelligence_return_to")
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, session: Session = Depends(database_session)) -> Response:
    settings = request.app.state.settings
    IdentityService(session).revoke_session(request.cookies.get(settings.auth_session_cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.auth_session_cookie_name)
    return response


@router.get("/me")
def me(user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, str | bool]:
    return {
        "id": str(user.id),
        "email": user.email,
        "is_platform_staff": PlatformStaffAccessService(session).is_platform_staff(user_id=user.id),
    }


@router.post("/organizations", status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreateInput,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    organization, _, membership = OrganizationService(session).create_organization(
        name=payload.name, owner_email=user.email, owner_user_id=user.id
    )
    return {"id": str(organization.id), "membership_id": str(membership.id), "role": membership.role.value}


@router.get("/organizations")
def organizations(user: User = Depends(current_user), session: Session = Depends(database_session)) -> list[dict[str, str]]:
    rows = OrganizationService(session).organizations_for_user(user_id=user.id)
    return [{"id": str(organization.id), "name": organization.name, "membership_id": str(membership.id), "role": membership.role.value} for organization, membership in rows]


@router.get("/organizations/{organization_id}/members")
def organization_members(
    organization_id: UUID, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> list[dict[str, str]]:
    try:
        rows = OrganizationService(session).members(scope=OrganizationScope(organization_id), actor_user_id=user.id)
    except InvitationNotAllowed as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return [{"id": str(membership.id), "email": member.email, "role": membership.role.value} for membership, member in rows]


@router.patch("/organizations/{organization_id}/members/{membership_id}")
def update_member_role(
    organization_id: UUID,
    membership_id: UUID,
    payload: MembershipRoleUpdateInput,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        membership = OrganizationService(session).change_membership_role(
            scope=OrganizationScope(organization_id), actor_user_id=user.id, membership_id=membership_id, role=payload.role
        )
    except InvitationNotAllowed as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except InvitationInvalid as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found") from error
    return {"id": str(membership.id), "role": membership.role.value}


@router.post("/organizations/{organization_id}/members/invitations", status_code=status.HTTP_202_ACCEPTED)
def create_invitation(
    organization_id: UUID,
    payload: InvitationCreateInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        invitation, raw_token = OrganizationService(session).create_invitation(
            scope=OrganizationScope(organization_id), actor_user_id=user.id, email=str(payload.email), role=payload.role
        )
        delivery: InvitationDeliveryPort = request.app.state.invitation_delivery
        delivery.send(
            recipient=invitation.email,
            invitation_url=f"{request.app.state.settings.public_app_url}/invitations/{raw_token}",
        )
    except InvitationNotAllowed as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="invitation unavailable") from error
    return {"status": "sent"}


@router.post("/invitations/{token}/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(
    token: str,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        membership = OrganizationService(session).accept_invitation(raw_token=token, user=user)
    except InvitationInvalid as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found") from error
    return {"organization_id": str(membership.organization_id), "role": membership.role.value}


@router.post("/organizations/{organization_id}/members/invitations/{invitation_id}/revoke", status_code=204)
def revoke_invitation(
    organization_id: UUID,
    invitation_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> Response:
    try:
        OrganizationService(session).revoke_invitation(
            scope=OrganizationScope(organization_id), actor_user_id=user.id, invitation_id=invitation_id
        )
    except InvitationNotAllowed as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except InvitationInvalid as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/organizations/{organization_id}/members/{membership_id}", status_code=204)
def deactivate_membership(
    organization_id: UUID,
    membership_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> Response:
    try:
        membership = OrganizationService(session).deactivate_membership(
            scope=OrganizationScope(organization_id), actor_user_id=user.id, membership_id=membership_id
        )
    except InvitationNotAllowed as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except InvitationInvalid as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found") from error
    IdentityService(session).revoke_user_sessions(user_id=membership.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
