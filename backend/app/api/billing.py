"""Plans catalog, account-type transitions and provider-agnostic billing endpoints (ADR-0022)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.billing.provider import BillingProvider, CheckoutRequest, PortalRequest, WebhookRejected
from app.billing.service import BillingService
from app.core.config import Settings
from app.entitlements import service as guards
from app.entitlements.catalog import (
    BUSINESS,
    PERSONAL,
    account_type_of,
    is_sellable,
    plan_for,
    sellable_plans,
)
from app.entitlements.errors import BillingNotConfigured, EntitlementError
from app.entitlements.resolver import current_subscription, entitlements_for
from app.entitlements.summary import plan_state
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole, Organization

public_router = APIRouter(tags=["plans"])
router = APIRouter(tags=["billing"])


def _provider(request: Request) -> BillingProvider:
    return request.app.state.billing_provider


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_owner(session: Session, organization_id: UUID, user_id: UUID) -> None:
    owner = session.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id,
        Membership.is_active.is_(True), Membership.role == MembershipRole.OWNER))
    if owner is None:
        raise HTTPException(403, "owner required")


def _require_member(session: Session, organization_id: UUID, user_id: UUID) -> None:
    member = session.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id, Membership.is_active.is_(True)))
    if member is None:
        raise HTTPException(403, "not allowed")


def plan_json(plan, *, settings: Settings) -> dict[str, object]:
    return {
        "plan_key": plan.plan_key, "account_type": plan.account_type, "title": plan.title,
        "price_month_cents": plan.price_month_cents, "price_year_cents": plan.price_year_cents,
        "currency": "BRL", "included_seats": plan.included_seats, "max_seats": plan.max_seats,
        "extra_seat_month_cents": plan.extra_seat_month_cents, "extra_seat_year_cents": plan.extra_seat_year_cents,
        "can_have_members": plan.can_have_members,
        "limits": {
            "max_spaces": plan.max_spaces, "active_documents": plan.active_documents,
            "monthly_processed_bytes": plan.monthly_processed_bytes,
            "monthly_embedding_tokens": plan.monthly_embedding_tokens, "monthly_questions": plan.monthly_questions,
            "monthly_ocr_pages": plan.monthly_ocr_pages, "max_file_bytes": plan.max_file_bytes,
            "max_automations": plan.max_automations, "max_api_keys": plan.max_api_keys,
            "max_data_sources": plan.max_data_sources, "audit_log_retention_days": plan.audit_log_retention_days,
        },
        "features": {
            "mcp": plan.mcp_enabled, "public_api": plan.public_api_enabled, "webhooks": plan.webhooks_enabled,
            "audit_panel": plan.audit_panel_enabled, "sso": plan.sso_enabled,
            "providers": list(plan.allowed_providers) if plan.allowed_providers is not None else None,
        },
    }


@public_router.get("/plans")
def plans(request: Request, response: Response) -> dict[str, object]:
    """Public catalog for the landing page / pricing screens. Prices are integer cents in BRL."""
    settings = _settings(request)
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "currency": "BRL", "trial_days": settings.trial_days, "trial_requires_card": False,
        "billing_configured": bool(_provider(request).configured),
        "plans": [plan_json(plan, settings=settings) for plan in sellable_plans()],
    }


@public_router.post("/webhooks/billing/{provider_name}")
async def billing_webhook(provider_name: str, request: Request, session: Session = Depends(database_session)):
    """Public (signature-verified by the provider adapter). With no provider configured: 501 billing_not_configured."""
    provider = _provider(request)
    if not provider.configured or provider.name != provider_name:
        raise BillingNotConfigured
    body = await request.body()
    try:
        outcome = BillingService(session, provider, _settings(request)).handle_webhook(body=body, headers=request.headers)
    except WebhookRejected as error:
        raise HTTPException(400, "webhook rejected") from error
    return {"status": outcome}


class UpgradeInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    plan_key: Literal["business_team", "business_scale"] = "business_team"
    seats: int = Field(default=5, ge=1, le=100)
    interval: Literal["month", "year"] = "month"


class DowngradeInput(BaseModel):
    plan_key: Literal["personal_basic", "personal_pro"] = "personal_basic"


@router.post("/organizations/{organization_id}/upgrade")
def upgrade(organization_id: UUID, payload: UpgradeInput, request: Request, user: User = Depends(current_user),
            session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    org = guards.upgrade_to_business(
        session, organization_id=organization_id, actor_user_id=user.id, name=payload.name, plan_key=payload.plan_key,
        seats=payload.seats, interval=payload.interval, provider=_provider(request), settings=_settings(request))
    return {"id": str(org.id), "name": org.name} | plan_state(entitlements_for(session, org.id))


@router.post("/organizations/{organization_id}/downgrade")
def downgrade(organization_id: UUID, request: Request, payload: DowngradeInput | None = None,
              user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    plan_key = payload.plan_key if payload else None
    org = guards.downgrade_to_personal(
        session, organization_id=organization_id, actor_user_id=user.id, plan_key=plan_key,
        provider=_provider(request), settings=_settings(request))
    return {"id": str(org.id), "name": org.name, "paused_automations": getattr(org, "_paused_automations", 0)} | plan_state(
        entitlements_for(session, org.id))


@router.get("/organizations/{organization_id}/billing")
def billing_state(organization_id: UUID, request: Request, user: User = Depends(current_user),
                  session: Session = Depends(database_session)) -> dict[str, object]:
    _require_member(session, organization_id, user.id)
    org = session.get(Organization, organization_id)
    ent = entitlements_for(session, organization_id)
    sub = current_subscription(session, organization_id)
    return plan_state(ent) | {
        "billing_configured": bool(_provider(request).configured), "provider": _provider(request).name,
        "legacy": ent.source == "legacy", "seats_used": guards.active_member_count(session, organization_id),
        "comp_expires_at": ent.comp_expires_at.isoformat() if ent.comp_expires_at else None,
        "grace_ends_at": ent.grace_ends_at.isoformat() if ent.grace_ends_at else None,
        "subscription": None if sub is None else {
            "status": sub.status, "plan_key": sub.plan_key, "interval": sub.interval, "seats": sub.seats,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end, "coupon_code": sub.coupon_code,
            "discount_summary": sub.discount_summary},
        "account_type_changed_at": org.account_type_changed_at.isoformat() if org and org.account_type_changed_at else None,
    }


class CheckoutInput(BaseModel):
    plan_key: str
    interval: Literal["month", "year"] = "month"
    seats: int = Field(default=1, ge=1, le=100)
    promotion_code: str | None = Field(default=None, max_length=64)


@router.post("/organizations/{organization_id}/billing/checkout")
def checkout(organization_id: UUID, payload: CheckoutInput, request: Request, user: User = Depends(current_user),
             session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    provider = _provider(request)
    if not provider.configured:
        raise BillingNotConfigured
    org = session.get(Organization, organization_id)
    if not is_sellable(payload.plan_key) or account_type_of(payload.plan_key) != org.account_type:
        raise EntitlementError("invalid_plan", "plan does not match the account type", status_code=422)
    plan = plan_for(payload.plan_key, _settings(request))
    if plan.max_seats is not None and payload.seats > plan.max_seats:
        raise EntitlementError("invalid_seats", "seat count outside the plan range", limit=plan.max_seats, status_code=422)
    if org.account_type == PERSONAL and payload.seats != 1:
        raise EntitlementError("invalid_seats", "personal plans have one seat", limit=1, status_code=422)
    members = guards.active_member_count(session, organization_id)
    if payload.seats < min(members, plan.max_seats or members):
        raise EntitlementError("seats_below_members", "fewer seats than active members", limit=members, status_code=409)
    app_url = _settings(request).public_app_url
    result = provider.create_checkout(CheckoutRequest(
        organization_id=organization_id, plan_key=payload.plan_key, interval=payload.interval, seats=payload.seats,
        customer_email=user.email, external_customer_id=org.billing_customer_id, promotion_code=payload.promotion_code,
        success_url=f"{app_url}/app/billing", cancel_url=f"{app_url}/app/billing"))
    if result.external_customer_id and not org.billing_customer_id:
        org.billing_provider, org.billing_customer_id = provider.name, result.external_customer_id
    return {"url": result.url}


@router.post("/organizations/{organization_id}/billing/portal")
def portal(organization_id: UUID, request: Request, user: User = Depends(current_user),
           session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    provider = _provider(request)
    if not provider.configured:
        raise BillingNotConfigured
    org = session.get(Organization, organization_id)
    result = provider.open_portal(PortalRequest(
        organization_id=organization_id, external_customer_id=org.billing_customer_id,
        return_url=f"{_settings(request).public_app_url}/app/billing"))
    return {"url": result.url}


class ChangePlanInput(BaseModel):
    plan_key: str
    interval: Literal["month", "year"] = "month"
    seats: int = Field(default=1, ge=1, le=100)


@router.post("/organizations/{organization_id}/billing/change-plan")
def change_plan(organization_id: UUID, payload: ChangePlanInput, request: Request, user: User = Depends(current_user),
                session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    provider = _provider(request)
    if not provider.configured:
        raise BillingNotConfigured
    org = session.get(Organization, organization_id)
    sub = current_subscription(session, organization_id)
    if sub is None:
        raise EntitlementError("subscription_required", "no active subscription", status_code=409)
    if not is_sellable(payload.plan_key) or account_type_of(payload.plan_key) != org.account_type:
        raise EntitlementError("invalid_plan", "plan does not match the account type", status_code=422)
    plan = plan_for(payload.plan_key, _settings(request))
    members = guards.active_member_count(session, organization_id)
    if (plan.max_seats is not None and payload.seats > plan.max_seats) or payload.seats < members:
        raise EntitlementError("invalid_seats", "seat count outside the plan range or below active members",
                               limit=plan.max_seats, used=members, status_code=409)
    provider.change_plan(subscription=sub, plan_key=payload.plan_key, interval=payload.interval, seats=payload.seats)
    sub.plan_key, sub.interval, sub.seats = payload.plan_key, payload.interval, payload.seats
    session.flush()
    from app.entitlements.resolver import project
    project(session, org, _settings(request))
    return plan_state(entitlements_for(session, organization_id))


@router.post("/organizations/{organization_id}/billing/cancel")
def cancel(organization_id: UUID, request: Request, user: User = Depends(current_user),
           session: Session = Depends(database_session)) -> dict[str, object]:
    _require_owner(session, organization_id, user.id)
    provider = _provider(request)
    if not provider.configured:
        raise BillingNotConfigured
    sub = current_subscription(session, organization_id)
    if sub is None:
        raise EntitlementError("subscription_required", "no active subscription", status_code=409)
    provider.cancel(subscription=sub, at_period_end=True)
    sub.cancel_at_period_end = True
    session.flush()
    from app.entitlements.resolver import invalidate
    invalidate(session, organization_id)
    return plan_state(entitlements_for(session, organization_id))


__all__ = ["BUSINESS", "public_router", "router"]
