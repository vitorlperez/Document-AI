"""HTTP boundary for AuthKit sessions and internal organization invitations."""

import secrets
from collections.abc import Generator
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.identity.auth import (
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
    HostedAuthenticationRequired,
    IdentityService,
    PendingEmailVerification,
    VerifiedIdentity,
    canonical_email,
    hash_secret,
)
from app.identity.client_ip import auth_client_ip
from app.identity.models import AuthIdentity, User
from app.identity.verification_context import (
    CONTEXT_COOKIE,
    make_verification_context,
    read_verification_context,
)
from app.organizations.delivery import InvitationDeliveryPort
from app.organizations.models import MembershipRole
from app.organizations.service import InvitationInvalid, InvitationNotAllowed, OrganizationService
from app.organizations.staff_access import PlatformStaffAccessService


class AuthRoute(APIRoute):
    """Never echo submitted credentials in validation error responses."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                if not request.url.path.startswith("/auth/"):
                    raise
                return JSONResponse(
                    {"detail": "Confira os dados informados e tente novamente."},
                    status_code=422,
                    headers={"cache-control": "no-store"},
                )

        return handler


router = APIRouter(tags=["authentication"], route_class=AuthRoute)


def _safe_invitation_return_to(value: str | None) -> str | None:
    """Accept only an opaque invitation path; never redirect a login externally."""
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path != value:
        return None
    prefix = "/invitations/"
    if not parsed.path.startswith(prefix):
        return None
    token = parsed.path.removeprefix(prefix)
    if not token.isascii() or not 20 <= len(token) <= 128 or not all(character.isalnum() or character in "_-" for character in token):
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


PENDING_VERIFICATION_COOKIE = "document_intelligence_pending_verification"


class PasswordInput(BaseModel):
    email: EmailStr
    password: SecretStr
    return_to: str | None = Field(default=None, max_length=256)


class VerificationInput(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    return_to: str | None = Field(default=None, max_length=256)


class ResetRequestInput(BaseModel):
    email: EmailStr


class RegistrationInput(ResetRequestInput):
    return_to: str | None = Field(default=None, max_length=256)


class ResetConfirmInput(BaseModel):
    token: SecretStr
    password: SecretStr


def _limit_auth(request: Request, email: str | None = None, *, token: str | None = None) -> None:
    peer = auth_client_ip(request)
    keys = [(f"auth:ip:{peer}", 60)]
    if email:
        keys.append((f"auth:email:{hash_secret(canonical_email(email))}", 10))
    if token:
        keys.append((f"auth:verification:{hash_secret(token)}", 5))
    try:
        for key, limit in keys:
            decision = request.app.state.rate_limiter.hit(key=key, limit=limit)
            if not decision.allowed:
                raise HTTPException(429, "Muitas tentativas. Aguarde um minuto e tente novamente.", headers={"Retry-After": str(decision.reset_seconds)})
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- limiter outages must fail closed
        raise HTTPException(503, "authentication unavailable") from None


def _password(value: SecretStr, *, new: bool = False) -> str:
    password = value.get_secret_value()
    if not (8 if new else 1) <= len(password) <= 1024:
        raise HTTPException(400, "A senha deve ter entre 8 e 1024 caracteres." if new else "Confira a senha informada.")
    return password


def _custom_auth_result(request: Request, session: Session, result, return_to: str | None) -> Response:
    settings = request.app.state.settings
    if isinstance(result, PendingEmailVerification):
        response = JSONResponse({"status": "email_verification_required"})
        response.set_cookie(PENDING_VERIFICATION_COOKIE, result.token, httponly=True, secure=settings.environment != "development", samesite="lax", max_age=600)
        if result.verification_id:
            context = make_verification_context(request, result.token, result.verification_id)
            response.set_cookie(CONTEXT_COOKIE, context, httponly=True, secure=settings.environment != "development", samesite="lax", max_age=600)
        else:
            response.delete_cookie(CONTEXT_COOKIE)
        return response
    if isinstance(result, HostedAuthenticationRequired):
        response = JSONResponse({"status": "hosted_authentication_required"})
        response.delete_cookie(PENDING_VERIFICATION_COOKIE)
        response.delete_cookie(CONTEXT_COOKIE)
        return response
    if not isinstance(result, VerifiedIdentity):
        raise HTTPException(401, "authentication failed")
    service = IdentityService(session)
    user = service.establish_identity(result)
    _, raw_session = service.create_session(user_id=user.id, ttl_hours=settings.auth_session_ttl_hours, provider_session_id=result.provider_session_id)
    safe_return = _safe_invitation_return_to(return_to)
    destination = f"{settings.public_app_url.rstrip('/')}{safe_return}" if safe_return else settings.public_app_url
    response = JSONResponse({"status": "authenticated", "redirect_url": destination})
    response.set_cookie(settings.auth_session_cookie_name, raw_session, httponly=True, secure=settings.environment != "development", samesite="lax", max_age=settings.auth_session_ttl_hours * 3600)
    for cookie in (PENDING_VERIFICATION_COOKIE, CONTEXT_COOKIE, settings.auth_login_state_cookie_name, "document_intelligence_return_to", "document_intelligence_force_reauthentication"):
        response.delete_cookie(cookie)
    return response


def _gateway_call(operation, **kwargs):
    try:
        return operation(**kwargs)
    except AuthenticationRejected as error:
        raise HTTPException(400, str(error)) from None
    except AuthenticationRateLimited as error:
        raise HTTPException(429, "Muitas tentativas. Aguarde e tente novamente.", headers={"Retry-After": str(error.retry_after)}) from None
    except AuthenticationUnavailable:
        raise HTTPException(503, "authentication unavailable") from None


@router.post("/auth/password")
def password_login(payload: PasswordInput, request: Request, session: Session = Depends(database_session)) -> Response:
    _limit_auth(request, str(payload.email))
    result = _gateway_call(request.app.state.auth_gateway.authenticate_password, email=str(payload.email), password=_password(payload.password), ip_address=auth_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _custom_auth_result(request, session, result, payload.return_to)


@router.post("/auth/register")
def password_register(payload: RegistrationInput, request: Request) -> Response:
    _limit_auth(request, str(payload.email))
    _gateway_call(request.app.state.auth_gateway.register_account, email=str(payload.email), ip_address=auth_client_ip(request), user_agent=request.headers.get("user-agent"))
    response = JSONResponse({"status": "registration_pending"})
    safe_return = _safe_invitation_return_to(payload.return_to)
    if safe_return:
        settings = request.app.state.settings
        response.set_cookie("document_intelligence_return_to", safe_return, httponly=True, secure=settings.environment != "development", samesite="lax", max_age=3600)
    return response


@router.post("/auth/verify-email")
def verify_email(payload: VerificationInput, request: Request, session: Session = Depends(database_session)) -> Response:
    token = request.cookies.get(PENDING_VERIFICATION_COOKIE)
    if not token or len(token) > 4096:
        raise HTTPException(400, "A confirmação expirou. Entre novamente para receber um novo código.")
    _limit_auth(request, token=token)
    result = _gateway_call(request.app.state.auth_gateway.verify_email, token=token, code=payload.code, ip_address=auth_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _custom_auth_result(request, session, result, payload.return_to)


@router.post("/auth/verify-email/resend")
def resend_verification(request: Request) -> dict[str, str]:
    token = request.cookies.get(PENDING_VERIFICATION_COOKIE)
    if not token or len(token) > 4096:
        raise HTTPException(400, "A confirmação expirou. Entre novamente para receber um novo código.")
    verification_id = read_verification_context(request, token)
    _limit_auth(request, token=token)
    try:
        decision = request.app.state.rate_limiter.hit(key=f"auth:resend:{hash_secret(verification_id)}", limit=1)
    except Exception:  # noqa: BLE001 -- limiter failures must fail closed
        raise HTTPException(503, "authentication unavailable") from None
    if not decision.allowed:
        raise HTTPException(429, "Aguarde um minuto antes de reenviar.", headers={"Retry-After": str(decision.reset_seconds)})
    _gateway_call(request.app.state.auth_gateway.resend_verification, verification_id=verification_id)
    return {"status": "sent"}


@router.post("/auth/password-reset")
def request_password_reset(payload: ResetRequestInput, request: Request) -> dict[str, str]:
    _limit_auth(request, str(payload.email))
    _gateway_call(request.app.state.auth_gateway.request_password_reset, email=str(payload.email))
    return {"status": "sent"}


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(payload: ResetConfirmInput, request: Request, session: Session = Depends(database_session)) -> Response:
    _limit_auth(request)
    token = payload.token.get_secret_value()
    if not token or len(token) > 4096:
        raise HTTPException(400, "Este link não é válido. Solicite um novo link.")
    subject = _gateway_call(request.app.state.auth_gateway.confirm_password_reset, token=token, password=_password(payload.password, new=True))
    identity = session.scalar(select(AuthIdentity).where(AuthIdentity.provider == "workos", AuthIdentity.provider_subject == subject))
    if identity:
        IdentityService(session).revoke_user_sessions(user_id=identity.user_id)
    # WorkOS confirms the reset and automatically revokes its active sessions.
    # Persist every local revocation before returning; no remote retry or marker.
    session.commit()
    result = {"status": "password_reset"}
    safe_return = _safe_invitation_return_to(request.cookies.get("document_intelligence_return_to"))
    if safe_return:
        result["return_to"] = safe_return
    response = JSONResponse(result)
    settings = request.app.state.settings
    response.set_cookie("document_intelligence_force_reauthentication", "1", httponly=True, secure=settings.environment != "development", samesite="lax", max_age=600)
    response.delete_cookie(request.app.state.settings.auth_session_cookie_name)
    response.delete_cookie(PENDING_VERIFICATION_COOKIE)
    response.delete_cookie(CONTEXT_COOKIE)
    return response


@router.get("/auth/login")
def login(
    request: Request,
    return_to: str | None = None,
    screen_hint: Literal["sign-in", "sign-up"] | None = None,
    force_reauthentication: bool = False,
) -> RedirectResponse:
    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
    force_reauthentication = force_reauthentication or request.cookies.get("document_intelligence_force_reauthentication") == "1"
    try:
        authorization_url = request.app.state.auth_gateway.authorization_url(
            state=state,
            screen_hint=screen_hint,
            max_age=0 if force_reauthentication else None,
        )
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
    response.delete_cookie("document_intelligence_force_reauthentication")
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
    _, raw_session = service.create_session(
        user_id=user.id,
        ttl_hours=settings.auth_session_ttl_hours,
        provider_session_id=identity.provider_session_id,
    )
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


@router.post("/auth/logout")
def logout(request: Request, session: Session = Depends(database_session)) -> Response:
    settings = request.app.state.settings
    provider_session_id = IdentityService(session).revoke_session(request.cookies.get(settings.auth_session_cookie_name))
    redirect_url = f"{settings.public_app_url.rstrip('/')}/login"
    if provider_session_id:
        try:
            request.app.state.auth_gateway.revoke_provider_session(session_id=provider_session_id)
        except AuthenticationUnavailable:
            # The local session is still revoked. A fresh AuthKit challenge on
            # the next login prevents an old provider session being reused.
            pass
    response = JSONResponse({"redirect_url": redirect_url})
    response.delete_cookie(settings.auth_session_cookie_name)
    response.set_cookie(
        "document_intelligence_force_reauthentication",
        "1",
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=600,
    )
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
