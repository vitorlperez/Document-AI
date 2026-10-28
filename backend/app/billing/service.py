"""Applies normalized provider events to the local subscription mirror (idempotent, order-safe)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing.provider import (
    EVENT_IGNORED,
    EVENT_PAYMENT_FAILED,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_RISK_FLAGGED,
    EVENT_SUBSCRIPTION_CANCELED,
    EVENT_TYPES,
    SUBSCRIPTION_STATUSES,
    BillingEvent,
    BillingProvider,
    WebhookRejected,
)
from app.core.config import Settings
from app.entitlements.catalog import account_type_of, is_sellable
from app.entitlements.resolver import invalidate, project
from app.organizations.models import BillingEvent as BillingEventRow
from app.organizations.models import Organization, Subscription

logger = logging.getLogger("document_intelligence.billing")


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class BillingService:
    def __init__(self, session: Session, provider: BillingProvider, settings: Settings):
        self.session, self.provider, self.settings = session, provider, settings

    def handle_webhook(self, *, body: bytes, headers) -> str:
        event = self.provider.parse_webhook(body=body, headers=headers)
        return self.apply_event(event)

    def apply_event(self, event: BillingEvent) -> str:
        """Returns ``processed`` | ``duplicate`` | ``ignored``. Same event twice or an older one never regresses state."""
        if event.type not in EVENT_TYPES:
            raise WebhookRejected("unknown event type")
        row_id = f"{self.provider.name}:{event.id}"
        if self.session.get(BillingEventRow, row_id) is not None:
            return "duplicate"
        try:
            with self.session.begin_nested():
                self.session.add(BillingEventRow(id=row_id, provider=self.provider.name, type=event.type))
                self.session.flush()
        except IntegrityError:
            return "duplicate"
        outcome = self._apply(event)
        self.session.get(BillingEventRow, row_id).processed_at = datetime.now(UTC)
        self.session.flush()
        return outcome

    def _find(self, event: BillingEvent) -> Subscription | None:
        if event.external_subscription_id is None:
            return None
        return self.session.scalar(select(Subscription).where(
            Subscription.provider == self.provider.name,
            Subscription.external_subscription_id == event.external_subscription_id))

    def _organization(self, event: BillingEvent, sub: Subscription | None) -> Organization | None:
        """Known subscription first, then the provider customer we stored, then the id the provider echoes back."""
        if sub is not None:
            return self.session.get(Organization, sub.organization_id)
        if event.external_customer_id:
            org = self.session.scalar(select(Organization).where(
                Organization.billing_provider == self.provider.name,
                Organization.billing_customer_id == event.external_customer_id))
            if org is not None:
                return org
        organization_id: UUID | None = event.organization_id
        org = self.session.get(Organization, organization_id) if organization_id else None
        if (org is not None and event.external_customer_id and org.billing_customer_id
                and org.billing_provider == self.provider.name and org.billing_customer_id != event.external_customer_id):
            # The metadata is writable by anyone with access to the provider account: it must not move an
            # organization onto a different customer. Ledger only, flagged for staff.
            logger.warning(
                "billing event %s names organization %s but customer %s differs from the stored one; ignored",
                event.id, org.id, event.external_customer_id,
                extra={"provider": self.provider.name, "event": event.type, "action": "staff_review"})
            return None
        return org

    def _note(self, event: BillingEvent) -> str:
        """Ledger-only events never touch a subscription or access. Risk signals alert staff through the log."""
        if event.type != EVENT_RISK_FLAGGED:
            return "ignored"
        org = self._organization(event, self._find(event))
        logger.warning(
            "billing risk flagged: event=%s organization=%s customer=%s subscription=%s", event.id,
            org.id if org is not None else None, event.external_customer_id, event.external_subscription_id,
            extra={"provider": self.provider.name, "event": event.type, "action": "staff_review"})
        return "processed"

    def _apply(self, event: BillingEvent) -> str:
        if event.type in (EVENT_RISK_FLAGGED, EVENT_IGNORED):
            return self._note(event)
        sub = self._find(event)
        org = self._organization(event, sub)
        if org is None:
            return "ignored"
        # Serialize concurrent webhooks of one organization, then re-read the row the stale check compares against.
        self.session.execute(select(Organization.id).where(Organization.id == org.id).with_for_update())
        if sub is not None:
            self.session.refresh(sub)
        if event.type in (EVENT_PAYMENT_FAILED, EVENT_PAYMENT_SUCCEEDED):
            if sub is None:
                return "ignored"
            if self._stale(sub, event):
                return "ignored"
            sub.past_due_since = (sub.past_due_since or event.occurred_at) if event.type == EVENT_PAYMENT_FAILED else None
            if event.type == EVENT_PAYMENT_FAILED and sub.status in {"active", "trialing"}:
                sub.status = "past_due"
            elif event.type == EVENT_PAYMENT_SUCCEEDED and sub.status == "past_due":
                sub.status = "active"
            self._touch(sub, event)
        else:
            if event.external_subscription_id is None:
                return "ignored"
            if sub is None:
                sub = Subscription(organization_id=org.id, provider=self.provider.name,
                                   external_subscription_id=event.external_subscription_id, plan_key="", status="incomplete")
                self.session.add(sub)
            elif self._stale(sub, event):
                return "ignored"
            self._copy(sub, event, canceled=event.type == EVENT_SUBSCRIPTION_CANCELED)
            self._touch(sub, event)
        if event.external_customer_id:
            org.billing_provider, org.billing_customer_id = self.provider.name, event.external_customer_id
        self.session.flush()
        self._project(org, sub)
        return "processed"

    @staticmethod
    def _stale(sub: Subscription, event: BillingEvent) -> bool:
        last = _aware(sub.last_event_at)
        return last is not None and _aware(event.occurred_at) < last

    @staticmethod
    def _touch(sub: Subscription, event: BillingEvent) -> None:
        sub.last_event_at = _aware(event.occurred_at)
        sub.updated_at = datetime.now(UTC)

    def _copy(self, sub: Subscription, event: BillingEvent, *, canceled: bool) -> None:
        # An unknown plan keeps the previous one: never silently demote on a catalog mismatch.
        if event.plan_key and is_sellable(event.plan_key):
            sub.plan_key = event.plan_key
        elif not sub.plan_key:
            raise WebhookRejected("unknown plan")
        status = "canceled" if canceled else (event.status or sub.status)
        if status not in SUBSCRIPTION_STATUSES:
            raise WebhookRejected("unknown status")
        sub.status = status
        if event.interval in {"month", "year"}:
            sub.interval = event.interval
        if event.seats is not None:
            sub.seats = max(1, event.seats)
        sub.external_customer_id = event.external_customer_id or sub.external_customer_id
        sub.current_period_end = _aware(event.current_period_end)
        sub.cancel_at = _aware(event.cancel_at)
        sub.cancel_at_period_end = event.cancel_at_period_end
        sub.coupon_code = event.coupon_code or sub.coupon_code
        sub.discount_summary = event.discount_summary or sub.discount_summary
        if status == "past_due":
            sub.past_due_since = sub.past_due_since or _aware(event.occurred_at)
        elif status in {"active", "trialing"}:
            sub.past_due_since = None

    def _project(self, org: Organization, sub: Subscription) -> None:
        # The subscription's plan decides the account type (a personal plan bought from a business org flips it back).
        if sub.plan_key and sub.status not in {"canceled", "incomplete", "incomplete_expired"}:
            target = account_type_of(sub.plan_key)
            if org.account_type != target:
                org.account_type, org.account_type_changed_at = target, datetime.now(UTC)
        invalidate(self.session, org.id)
        project(self.session, org, self.settings)
