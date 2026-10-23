"""``BillingProvider`` port + normalized events. No payment SDK is imported here (ADR-0022)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.entitlements.errors import BillingNotConfigured
from app.organizations.models import Subscription

EVENT_SUBSCRIPTION_UPSERTED = "subscription.upserted"
EVENT_SUBSCRIPTION_CANCELED = "subscription.canceled"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_PAYMENT_SUCCEEDED = "payment.succeeded"
EVENT_TYPES = {EVENT_SUBSCRIPTION_UPSERTED, EVENT_SUBSCRIPTION_CANCELED, EVENT_PAYMENT_FAILED, EVENT_PAYMENT_SUCCEEDED}
SUBSCRIPTION_STATUSES = {"active", "trialing", "past_due", "unpaid", "paused", "incomplete", "incomplete_expired", "canceled"}


@dataclass(frozen=True)
class CheckoutRequest:
    organization_id: UUID
    plan_key: str
    interval: str
    seats: int
    customer_email: str | None = None
    external_customer_id: str | None = None
    promotion_code: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None


@dataclass(frozen=True)
class CheckoutSession:
    url: str
    external_customer_id: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class PortalRequest:
    organization_id: UUID
    external_customer_id: str | None
    return_url: str | None = None


@dataclass(frozen=True)
class PortalSession:
    url: str


@dataclass(frozen=True)
class BillingEvent:
    """What every provider's webhook is normalized to before touching the database."""

    id: str
    type: str
    occurred_at: datetime
    organization_id: UUID | None = None
    external_customer_id: str | None = None
    external_subscription_id: str | None = None
    plan_key: str | None = None
    interval: str | None = None
    seats: int | None = None
    status: str | None = None
    current_period_end: datetime | None = None
    cancel_at: datetime | None = None
    cancel_at_period_end: bool = False
    coupon_code: str | None = None
    discount_summary: dict | None = None


class WebhookRejected(ValueError):
    """Bad signature or unparseable payload (HTTP 400)."""


@runtime_checkable
class BillingProvider(Protocol):
    name: str
    configured: bool

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession: ...

    def open_portal(self, request: PortalRequest) -> PortalSession: ...

    def change_plan(self, *, subscription: Subscription, plan_key: str, interval: str, seats: int) -> None: ...

    def cancel(self, *, subscription: Subscription, at_period_end: bool = True) -> None: ...

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> BillingEvent: ...


class NoBillingProvider:
    """Default: nothing is sold. Every operation answers ``billing_not_configured`` (HTTP 501)."""

    name = "none"
    configured = False

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        raise BillingNotConfigured

    def open_portal(self, request: PortalRequest) -> PortalSession:
        raise BillingNotConfigured

    def change_plan(self, *, subscription: Subscription, plan_key: str, interval: str, seats: int) -> None:
        raise BillingNotConfigured

    def cancel(self, *, subscription: Subscription, at_period_end: bool = True) -> None:
        raise BillingNotConfigured

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> BillingEvent:
        raise BillingNotConfigured


def build_provider(name: str) -> BillingProvider:
    """Registry for future adapters; an unknown or empty name never silently enables payments."""
    return NoBillingProvider()
