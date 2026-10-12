"""Outbound webhook endpoints of an organization; Owner/Admin only, secret shown once (specs/automations-api.md)."""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.automations.models import WebhookDelivery, WebhookEndpoint
from app.automations.webhooks import (
    EVENTS,
    BlockedDestination,
    hash_secret,
    new_secret,
    validate_destination,
)
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole

router = APIRouter(tags=["automation-webhooks"])
MAX_ACTIVE_ENDPOINTS = 5


class EndpointCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(default_factory=lambda: list(EVENTS), min_length=1, max_length=len(EVENTS))
    enabled: bool = True


class EndpointPatch(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    events: list[str] | None = Field(default=None, min_length=1, max_length=len(EVENTS))
    enabled: bool | None = None


def _require_admin(session: Session, organization_id: UUID, user: User) -> None:
    member = session.scalar(select(Membership).where(
        Membership.organization_id == organization_id, Membership.user_id == user.id, Membership.is_active.is_(True)))
    if member is None:
        raise HTTPException(403, "not allowed")
    if member.role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
        raise HTTPException(403, "owner or admin required")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validated_url(url: str) -> str:
    url = url.strip()
    try:
        validate_destination(url)
    except BlockedDestination as error:
        raise HTTPException(422, "invalid_webhook_url") from error
    return url


def _validated_events(events: list[str]) -> list[str]:
    if not set(events) <= set(EVENTS):
        raise HTTPException(422, "invalid_webhook_events")
    return sorted(set(events))


def _serialize(session: Session, endpoint: WebhookEndpoint) -> dict[str, object]:
    last = session.scalar(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
                          .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc()).limit(1))
    return {"id": str(endpoint.id), "url": endpoint.url, "events": endpoint.events, "enabled": endpoint.enabled,
            "revoked_at": _iso(endpoint.revoked_at), "created_at": _iso(endpoint.created_at),
            "created_by_user_id": str(endpoint.created_by_user_id),
            "last_delivery": None if last is None else {"id": str(last.id), "status": last.status, "attempts": last.attempts,
                                                        "created_at": _iso(last.created_at)}}


def _serialize_delivery(item: WebhookDelivery) -> dict[str, object]:
    return {"id": str(item.id), "event": item.event, "run_id": str(item.run_id), "status": item.status,
            "attempts": item.attempts, "last_error": item.last_error, "last_status_code": item.last_status_code,
            "created_at": _iso(item.created_at), "delivered_at": _iso(item.delivered_at)}


def _load(session: Session, organization_id: UUID, endpoint_id: UUID) -> WebhookEndpoint:
    endpoint = session.scalar(select(WebhookEndpoint).where(
        WebhookEndpoint.id == endpoint_id, WebhookEndpoint.organization_id == organization_id))
    if endpoint is None:
        raise HTTPException(404, "webhook endpoint not found")
    return endpoint


def _active_count(session: Session, organization_id: UUID, *, excluding: UUID | None = None) -> int:
    ids = session.scalars(select(WebhookEndpoint.id).where(
        WebhookEndpoint.organization_id == organization_id, WebhookEndpoint.revoked_at.is_(None))).all()
    return len([item for item in ids if item != excluding])


@router.get("/organizations/{organization_id}/webhook-endpoints")
def list_endpoints(organization_id: UUID, user: User = Depends(current_user),
                   session: Session = Depends(database_session)) -> dict[str, object]:
    _require_admin(session, organization_id, user)
    rows = session.scalars(select(WebhookEndpoint).where(WebhookEndpoint.organization_id == organization_id)
                           .order_by(WebhookEndpoint.revoked_at.is_not(None), WebhookEndpoint.created_at.desc(), WebhookEndpoint.id))
    return {"limit": MAX_ACTIVE_ENDPOINTS, "items": [_serialize(session, item) for item in rows]}


@router.post("/organizations/{organization_id}/webhook-endpoints", status_code=201)
def create_endpoint(organization_id: UUID, payload: EndpointCreate, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict[str, object]:
    _require_admin(session, organization_id, user)
    if _active_count(session, organization_id) >= MAX_ACTIVE_ENDPOINTS:
        raise HTTPException(409, "webhook_limit_reached")
    secret = new_secret()
    endpoint = WebhookEndpoint(organization_id=organization_id, created_by_user_id=user.id, url=_validated_url(payload.url),
                               secret_hash=hash_secret(secret), events=_validated_events(payload.events), enabled=payload.enabled)
    session.add(endpoint)
    session.flush()
    session.refresh(endpoint)
    return {**_serialize(session, endpoint), "secret": secret}


@router.patch("/organizations/{organization_id}/webhook-endpoints/{endpoint_id}")
def update_endpoint(organization_id: UUID, endpoint_id: UUID, payload: EndpointPatch, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict[str, object]:
    _require_admin(session, organization_id, user)
    endpoint = _load(session, organization_id, endpoint_id)
    if endpoint.revoked_at is not None:
        raise HTTPException(409, "webhook_revoked")
    if payload.url is not None:
        endpoint.url = _validated_url(payload.url)
    if payload.events is not None:
        endpoint.events = _validated_events(payload.events)
    if payload.enabled is not None:
        endpoint.enabled = payload.enabled
    session.flush()
    return _serialize(session, endpoint)


@router.post("/organizations/{organization_id}/webhook-endpoints/{endpoint_id}/rotate-secret")
def rotate_secret(organization_id: UUID, endpoint_id: UUID, user: User = Depends(current_user),
                  session: Session = Depends(database_session)) -> dict[str, object]:
    _require_admin(session, organization_id, user)
    endpoint = _load(session, organization_id, endpoint_id)
    if endpoint.revoked_at is not None:
        raise HTTPException(409, "webhook_revoked")
    secret = new_secret()
    endpoint.secret_hash = hash_secret(secret)
    session.flush()
    return {**_serialize(session, endpoint), "secret": secret}


@router.delete("/organizations/{organization_id}/webhook-endpoints/{endpoint_id}", status_code=204)
def revoke_endpoint(organization_id: UUID, endpoint_id: UUID, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> Response:
    _require_admin(session, organization_id, user)
    endpoint = _load(session, organization_id, endpoint_id)
    if endpoint.revoked_at is None:
        endpoint.revoked_at = datetime.now(UTC)
        endpoint.enabled = False
        for delivery in session.scalars(select(WebhookDelivery).where(
                WebhookDelivery.endpoint_id == endpoint.id, WebhookDelivery.status == "pending")):
            delivery.status, delivery.last_error = "failed", "endpoint_inactive"
    return Response(status_code=204)


@router.get("/organizations/{organization_id}/webhook-endpoints/{endpoint_id}/deliveries")
def list_deliveries(organization_id: UUID, endpoint_id: UUID, limit: int = Query(20, ge=1, le=100),
                    user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    _require_admin(session, organization_id, user)
    endpoint = _load(session, organization_id, endpoint_id)
    rows = session.scalars(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
                           .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc()).limit(limit))
    return {"items": [_serialize_delivery(item) for item in rows]}
