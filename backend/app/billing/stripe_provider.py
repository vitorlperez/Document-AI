"""Stripe adapter for the ``BillingProvider`` port (ADR-0023).

The ``stripe`` SDK is imported lazily, only when no client is injected, so the default deployment
(``BILLING_PROVIDER=none``) and the test suite never load it. Every call goes through a ``StripeClient`` instance
pinned to ``settings.stripe_api_version`` (never the deprecated global ``stripe.api_key``), using the SDK v16 shapes
``client.v1.<service>.<method>(..., params=..., options=...)``.

Webhooks are verified against the raw body, then the subscription is re-fetched so the mirror always reflects
Stripe's current state; the event's own ``created`` time orders events (``BillingService`` drops stale ones).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.billing.provider import (
    EVENT_IGNORED,
    EVENT_PAYMENT_FAILED,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_RISK_FLAGGED,
    EVENT_SUBSCRIPTION_CANCELED,
    EVENT_SUBSCRIPTION_UPSERTED,
    BillingEvent,
    CheckoutRequest,
    CheckoutSession,
    InvoiceSummary,
    PortalRequest,
    PortalSession,
    WebhookRejected,
)
from app.billing.stripe_catalog import (
    desired_price,
    get_field,
    lookup_key,
    max_charge_cents,
    normalize_interval,
    plan_from_price,
)
from app.entitlements.catalog import BUSINESS, account_type_of
from app.entitlements.errors import BillingNotConfigured, EntitlementError

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.organizations.models import Subscription

logger = logging.getLogger("document_intelligence.billing.stripe")

LOCALE = "pt-BR"
PRICE_CACHE_SECONDS = 300.0
# Nested expansion also expands the parent (``discounts``); price metadata carries plan_key, product is the fallback.
# ``discounts.source.coupon`` is needed for the coupon's name/percent_off/duration: without it ``source.coupon`` is
# only the coupon ID (verified against the sandbox, API 2026-09-30.endive).
SUBSCRIPTION_EXPAND = ["items.data.price.product", "discounts.promotion_code", "discounts.source.coupon"]

CHECKOUT_EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
}
SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.paused",
    "customer.subscription.resumed",
}
RISK_EVENTS = {"charge.dispute.created", "charge.refunded", "radar.early_fraud_warning.created"}
MANDATE_EVENT = "mandate.updated"
# Pix Automático mandate ``payment_schedule`` per billing interval (API enum: weekly/monthly/quarterly/halfyearly/yearly).
PIX_PAYMENT_SCHEDULE = {"month": "monthly", "year": "yearly"}
ENDED_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}


def _id(value: Any) -> str | None:
    """An expandable field is either an ID string or the expanded object."""
    if value is None or isinstance(value, str):
        return value or None
    return get_field(value, "id")


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value), UTC)


def _uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)  # Starlette headers are case-insensitive; plain dicts may not be
    if value is None:
        lowered = name.lower()
        value = next((v for k, v in headers.items() if str(k).lower() == lowered), None)
    return value


def _is_signature_error(error: Exception) -> bool:
    # stripe.SignatureVerificationError is not importable at module load (the SDK is optional), so match by name.
    return any(cls.__name__ == "SignatureVerificationError" for cls in type(error).__mro__)


def _is_card_error(error: Exception) -> bool:
    return any(cls.__name__ == "CardError" for cls in type(error).__mro__)


def _is_invalid_request(error: Exception) -> bool:
    return any(cls.__name__ == "InvalidRequestError" for cls in type(error).__mro__)


def _require_seats(seats: Any) -> int:
    """Seat counts come from the API layer; anything below 1 is a client error, never silently clamped."""
    try:
        value = int(seats)
    except (TypeError, ValueError):
        value = 0
    if value < 1:
        raise EntitlementError("invalid_seats", "seats must be at least 1", status_code=422)
    return value


def _annualized_cents(plan_key: str | None, interval: str | None, seats: int | None) -> int | None:
    if not plan_key or not interval:
        return None
    try:
        total = desired_price(plan_key, interval).total_cents(max(1, int(seats or 1)))
    except (KeyError, ValueError):
        return None
    return total if normalize_interval(interval) == "year" else total * 12


class StripeBillingProvider:
    name = "stripe"
    configured = True

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        if client is None:
            api_key = settings.stripe_api_key.get_secret_value().strip() if settings.stripe_api_key else ""
            if not api_key:
                raise BillingNotConfigured
            import stripe  # lazy: only a stripe deployment loads the SDK

            client = stripe.StripeClient(api_key, stripe_version=settings.stripe_api_version, max_network_retries=2)
        self.client = client
        self._prices: dict[str, tuple[str, float]] = {}
        self._prices_lock = threading.Lock()

    # -- catalog ----------------------------------------------------------------------------------------------------

    def _price_id(self, plan_key: str, interval: str) -> str:
        """Price for a plan via its lookup key (prices are replaced, never edited, so the key follows the new one)."""
        key = lookup_key(plan_key, interval)
        now = time.monotonic()
        with self._prices_lock:
            cached = self._prices.get(key)
            if cached and cached[1] > now:
                return cached[0]
        page = self.client.v1.prices.list(params={"lookup_keys": [key], "active": True, "limit": 1})
        data = list(get_field(page, "data") or [])
        if not data:
            logger.error("stripe price missing for lookup key %s; run scripts/stripe_sync_catalog.py", key)
            raise EntitlementError("plan_unavailable", "plan is not available for purchase", status_code=503)
        price_id = get_field(data[0], "id")
        with self._prices_lock:
            self._prices[key] = (price_id, now + PRICE_CACHE_SECONDS)
        return price_id

    def _promotion_code_id(self, code: str) -> str:
        code = code.strip()
        if code.startswith("promo_"):
            return code
        page = self.client.v1.promotion_codes.list(params={"code": code, "active": True, "limit": 1})
        data = list(get_field(page, "data") or [])
        if not data:
            raise EntitlementError("invalid_promotion_code", "promotion code not found or inactive", status_code=422)
        return get_field(data[0], "id")

    # -- checkout / portal ------------------------------------------------------------------------------------------

    def _customer_id(self, request: CheckoutRequest) -> str:
        if request.external_customer_id:
            return request.external_customer_id
        params: dict[str, Any] = {
            "metadata": {"organization_id": str(request.organization_id)},
            "preferred_locales": [LOCALE],
        }
        if request.customer_email:
            params["email"] = request.customer_email
        customer = self.client.v1.customers.create(
            params=params, options={"idempotency_key": f"org-{request.organization_id}-customer"})
        return get_field(customer, "id")

    @property
    def _pix_enabled(self) -> bool:
        return bool(getattr(self.settings, "stripe_pix_enabled", False))

    @staticmethod
    def _pix_mandate_options(plan_key: str, interval: str) -> dict[str, Any]:
        """Pix Automático mandate: a ceiling (not a fixed amount) covering the plan at ``max_seats`` so in-plan seat
        changes never exceed it. Plan or interval changes beyond it need a new mandate (see ``change_plan``)."""
        interval = normalize_interval(interval)
        return {
            "amount": max_charge_cents(plan_key, interval),
            "amount_type": "maximum",
            "currency": "brl",
            "payment_schedule": PIX_PAYMENT_SCHEDULE[interval],
            "reference": f"Arquivio {plan_key}",
        }

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        seats = _require_seats(request.seats)
        price_id = self._price_id(request.plan_key, request.interval)
        customer_id = self._customer_id(request)
        organization_id = str(request.organization_id)
        metadata = {"organization_id": organization_id, "plan_key": request.plan_key,
                    "interval": normalize_interval(request.interval)}
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": organization_id,
            "line_items": [{"price": price_id, "quantity": seats}],
            # Explicit (it is the API default for this version) so prorations behave the same if the default moves.
            "subscription_data": {"metadata": metadata, "billing_mode": {"type": "flexible"}},
            "metadata": metadata,
            "locale": LOCALE,
            "integration_identifier": self.settings.stripe_checkout_integration_id,
            # No payment_method_types: dynamic payment methods are configured in the Dashboard.
            # No automatic_tax, ever: Stripe Tax does not support BR accounts (NFS-e is issued outside Stripe).
            # No ui_mode: the default hosted page is used.
        }
        if request.success_url:
            params["success_url"] = request.success_url
        if request.cancel_url:
            params["cancel_url"] = request.cancel_url
        if account_type_of(request.plan_key) == BUSINESS:
            params["billing_address_collection"] = "required"
            # Best effort (BR CPF/CNPJ may not be offered by Checkout); never ``required``.
            params["tax_id_collection"] = {"enabled": True}
            # An existing Customer only stores the collected name/address/tax ID when allowed to be updated.
            params["customer_update"] = {"name": "auto", "address": "auto"}
        if self._pix_enabled:
            params["payment_method_options"] = {
                "pix": {"mandate_options": self._pix_mandate_options(request.plan_key, request.interval)}}
        if request.promotion_code:
            params["discounts"] = [{"promotion_code": self._promotion_code_id(request.promotion_code)}]
        else:
            params["allow_promotion_codes"] = True  # mutually exclusive with discounts
        try:
            session = self.client.v1.checkout.sessions.create(params=params)
        except Exception as error:
            # A ``promo_...`` id is passed through unchecked; Stripe rejects an unknown/ineligible one on the discounts param.
            if request.promotion_code and _is_invalid_request(error) and any(
                    part in str(getattr(error, "param", "") or "") for part in ("promotion_code", "discounts")):
                raise EntitlementError("invalid_promotion_code", "promotion code not found or inactive",
                                       status_code=422) from error
            raise
        return CheckoutSession(url=get_field(session, "url"), external_customer_id=customer_id,
                               external_id=get_field(session, "id"))

    def open_portal(self, request: PortalRequest) -> PortalSession:
        if not request.external_customer_id:
            raise EntitlementError("subscription_required", "no billing customer yet", status_code=409)
        params: dict[str, Any] = {"customer": request.external_customer_id, "locale": LOCALE}
        if request.return_url:
            params["return_url"] = request.return_url
        if self.settings.stripe_portal_configuration_id:
            params["configuration"] = self.settings.stripe_portal_configuration_id
        session = self.client.v1.billing_portal.sessions.create(params=params)
        return PortalSession(url=get_field(session, "url"))

    # -- subscription changes ---------------------------------------------------------------------------------------

    def change_plan(self, *, subscription: Subscription, plan_key: str, interval: str, seats: int) -> None:
        """Raises (nothing is written locally) unless Stripe accepted the change and, on upgrade, its payment.

        Pix Automático: a subscription paid by Pix can only be charged up to its mandate ceiling (set at checkout to
        ``max_charge_cents`` of the plan/interval it was bought with) and no more often than the mandate schedule. A
        change beyond that raises ``pix_mandate_reauth_required`` (409) before anything is sent, so the customer can be
        sent through a new checkout. Detection is best effort: only the subscription's own ``default_payment_method``
        is inspected (a customer-level default is not).
        """
        seats = _require_seats(seats)
        sub_id = subscription.external_subscription_id
        expand = ["items.data.price", "default_payment_method"] if self._pix_enabled else ["items.data.price"]
        current = self.client.v1.subscriptions.retrieve(sub_id, params={"expand": expand})
        items = list(get_field(get_field(current, "items"), "data") or [])
        if len(items) != 1:
            raise EntitlementError("subscription_unsupported", "subscription has an unexpected item layout",
                                   status_code=409)
        item = items[0]
        old_plan, old_interval = plan_from_price(get_field(item, "price"))
        old_total = _annualized_cents(old_plan or subscription.plan_key, old_interval or subscription.interval,
                                      get_field(item, "quantity") or subscription.seats)
        new_total = _annualized_cents(plan_key, interval, seats)
        upgrade = old_total is None or new_total is None or new_total > old_total
        if self._pix_enabled and self._pays_with_pix(current):
            self._check_pix_mandate(old_plan or subscription.plan_key, old_interval or subscription.interval,
                                    plan_key, interval, seats)
        params = {
            "items": [{"id": get_field(item, "id"), "price": self._price_id(plan_key, interval), "quantity": seats}],
            # Upgrades are charged now; downgrades credit the next invoice.
            "proration_behavior": "always_invoice" if upgrade else "create_prorations",
            # Fail the request instead of leaving the subscription past_due on a declined upgrade.
            "payment_behavior": "error_if_incomplete",
            "metadata": {"plan_key": plan_key, "interval": normalize_interval(interval)},
        }
        try:
            self.client.v1.subscriptions.update(
                sub_id, params=params, options={"idempotency_key": f"arquivio-change-{sub_id}-{uuid.uuid4().hex}"})
        except Exception as error:
            if _is_card_error(error):
                raise EntitlementError("payment_failed", "the payment for this change was declined",
                                       status_code=402) from error
            raise

    def _pays_with_pix(self, sub: Any) -> bool:
        payment_method = get_field(sub, "default_payment_method")
        if not payment_method:
            return False
        if isinstance(payment_method, str):
            payment_method = self.client.v1.payment_methods.retrieve(payment_method)
        return get_field(payment_method, "type") == "pix"

    @staticmethod
    def _check_pix_mandate(old_plan: str | None, old_interval: str | None, plan_key: str, interval: str,
                           seats: int) -> None:
        mandate_amount: int | None = None
        old_schedule: str | None = None
        new_amount = 0
        try:
            mandate_amount = max_charge_cents(old_plan, old_interval) if old_plan and old_interval else None
            old_schedule = normalize_interval(old_interval) if old_interval else None
            new_amount = desired_price(plan_key, interval).total_cents(seats)
        except (KeyError, ValueError):
            mandate_amount = None  # unknown plan/interval: cannot prove the change fits the mandate
        # A yearly mandate cannot be charged monthly; an unknown mandate is treated as too small.
        if mandate_amount is None or new_amount > mandate_amount or (
                old_schedule == "year" and normalize_interval(interval) == "month"):
            raise EntitlementError("pix_mandate_reauth_required",
                                   "this change exceeds the Pix Automático authorization; a new checkout is required",
                                   status_code=409)

    def cancel(self, *, subscription: Subscription, at_period_end: bool = True) -> None:
        sub_id = subscription.external_subscription_id
        options = {"idempotency_key": f"arquivio-cancel-{sub_id}-{uuid.uuid4().hex}"}
        if at_period_end:
            self.client.v1.subscriptions.update(sub_id, params={"cancel_at_period_end": True}, options=options)
        else:
            self.client.v1.subscriptions.cancel(sub_id, options=options)

    # -- invoices ---------------------------------------------------------------------------------------------------

    def list_invoices(self, customer_id: str, limit: int = 12) -> list[InvoiceSummary]:
        if not customer_id:
            return []
        page = self.client.v1.invoices.list(params={"customer": customer_id, "limit": max(1, min(int(limit), 100))})
        invoices = []
        for invoice in get_field(page, "data") or []:
            if get_field(invoice, "status") == "draft":
                continue  # not final yet: no number, no hosted page
            invoices.append(InvoiceSummary(
                id=get_field(invoice, "id"), number=get_field(invoice, "number"), status=get_field(invoice, "status"),
                total=int(get_field(invoice, "total") or 0), currency=(get_field(invoice, "currency") or "").lower(),
                created=_timestamp(get_field(invoice, "created")) or datetime.now(UTC),
                hosted_invoice_url=get_field(invoice, "hosted_invoice_url"),
                invoice_pdf=get_field(invoice, "invoice_pdf")))
        return invoices

    # -- webhooks ---------------------------------------------------------------------------------------------------

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> BillingEvent:
        signature = _header(headers, "stripe-signature")
        secret = self.settings.stripe_webhook_secret.get_secret_value() if self.settings.stripe_webhook_secret else ""
        if not signature or not secret:
            raise WebhookRejected("missing signature")
        try:
            event = self.client.construct_event(body, signature, secret)
        except Exception as error:
            if _is_signature_error(error) or isinstance(error, ValueError):  # ValueError: unparseable payload
                raise WebhookRejected("invalid signature") from error
            raise
        event_id, event_type = get_field(event, "id"), get_field(event, "type") or ""
        if not event_id:
            raise WebhookRejected("event without id")
        occurred_at = _timestamp(get_field(event, "created")) or datetime.now(UTC)
        obj = get_field(get_field(event, "data"), "object") or {}
        base = {"id": event_id, "occurred_at": occurred_at}

        if event_type in CHECKOUT_EVENTS:
            sub_id = _id(get_field(obj, "subscription"))
            fallback_org = _uuid(get_field(obj, "client_reference_id")) or _uuid(
                get_field(get_field(obj, "metadata"), "organization_id"))
            if get_field(obj, "mode") != "subscription" or not sub_id:
                return BillingEvent(type=EVENT_IGNORED, organization_id=fallback_org,
                                    external_customer_id=_id(get_field(obj, "customer")), **base)
            # The refetched status gates access: an unpaid async payment leaves it "incomplete" (no grant).
            return self._subscription_event(EVENT_SUBSCRIPTION_UPSERTED, sub_id, base, fallback_org=fallback_org)
        if event_type in SUBSCRIPTION_EVENTS:
            return self._subscription_event(EVENT_SUBSCRIPTION_UPSERTED, get_field(obj, "id"), base)
        if event_type == "customer.subscription.deleted":
            return self._subscription_event(EVENT_SUBSCRIPTION_CANCELED, get_field(obj, "id"), base)
        if event_type in {"invoice.paid", "invoice.payment_failed"}:
            return self._invoice_event(obj, base, EVENT_PAYMENT_SUCCEEDED if event_type == "invoice.paid"
                                       else EVENT_PAYMENT_FAILED)
        if event_type == "invoice.payment_action_required":
            sub_id, _ = self._invoice_subscription(obj)
            if sub_id:
                return self._subscription_event(EVENT_SUBSCRIPTION_UPSERTED, sub_id, base)
            return BillingEvent(type=EVENT_IGNORED, external_customer_id=_id(get_field(obj, "customer")), **base)
        if event_type == MANDATE_EVENT:
            return self._mandate_event(obj, base)
        if event_type in RISK_EVENTS:
            return BillingEvent(type=EVENT_RISK_FLAGGED, external_customer_id=self._risk_customer(event_type, obj),
                                **base)
        customer = get_field(obj, "customer") if get_field(obj, "object") != "customer" else get_field(obj, "id")
        return BillingEvent(type=EVENT_IGNORED, external_customer_id=_id(customer), **base)

    def _subscription_event(self, kind: str, sub_id: str | None, base: dict[str, Any], *,
                            fallback_org: UUID | None = None) -> BillingEvent:
        if not sub_id:
            raise WebhookRejected("subscription event without id")
        sub = self.client.v1.subscriptions.retrieve(sub_id, params={"expand": SUBSCRIPTION_EXPAND})
        items = list(get_field(get_field(sub, "items"), "data") or [])
        item = items[0] if items else {}
        plan_key, interval = plan_from_price(get_field(item, "price"))
        coupon_code, discount_summary = self._discount(sub)
        quantity = get_field(item, "quantity")
        return BillingEvent(
            type=kind,
            organization_id=_uuid(get_field(get_field(sub, "metadata"), "organization_id")) or fallback_org,
            external_customer_id=_id(get_field(sub, "customer")),
            external_subscription_id=get_field(sub, "id") or sub_id,
            plan_key=plan_key,
            interval=interval,
            seats=int(quantity) if quantity is not None else None,
            status=get_field(sub, "status"),
            # Moved from the subscription to its items in recent API versions.
            current_period_end=_timestamp(get_field(item, "current_period_end")),
            cancel_at=_timestamp(get_field(sub, "cancel_at")),
            cancel_at_period_end=bool(get_field(sub, "cancel_at_period_end")),
            coupon_code=coupon_code,
            discount_summary=discount_summary,
            **base,
        )

    @staticmethod
    def _discount(sub: Any) -> tuple[str | None, dict | None]:
        discounts = [d for d in (get_field(sub, "discounts") or []) if not isinstance(d, str)]
        if not discounts:
            return None, None
        discount = discounts[0]
        # ``discount.coupon`` became ``discount.source.coupon`` in recent API versions; accept both shapes.
        coupon = get_field(discount, "coupon") or get_field(get_field(discount, "source"), "coupon")
        coupon_obj = coupon if coupon is not None and not isinstance(coupon, str) else {}
        promotion = get_field(discount, "promotion_code")
        promotion_code = get_field(promotion, "code") if promotion is not None and not isinstance(promotion, str) else None
        coupon_id = _id(coupon)
        summary = {
            "coupon_id": coupon_id,
            "promotion_code": promotion_code,
            "name": get_field(coupon_obj, "name"),
            "percent_off": get_field(coupon_obj, "percent_off"),
            "amount_off": get_field(coupon_obj, "amount_off"),
            "currency": get_field(coupon_obj, "currency"),
            "duration": get_field(coupon_obj, "duration"),
            "duration_in_months": get_field(coupon_obj, "duration_in_months"),
            "end": (_timestamp(get_field(discount, "end")).isoformat() if get_field(discount, "end") else None),
        }
        return (promotion_code or coupon_id), {key: value for key, value in summary.items() if value is not None}

    @staticmethod
    def _invoice_subscription(invoice: Any) -> tuple[str | None, Mapping | None]:
        # Recent API versions: invoice.parent.subscription_details.{subscription,metadata}; older: invoice.subscription.
        details = get_field(get_field(invoice, "parent"), "subscription_details")
        sub_id = _id(get_field(details, "subscription")) or _id(get_field(invoice, "subscription"))
        return sub_id, get_field(details, "metadata")

    def _invoice_event(self, invoice: Any, base: dict[str, Any], kind: str) -> BillingEvent:
        sub_id, metadata = self._invoice_subscription(invoice)
        return BillingEvent(
            type=kind,
            organization_id=_uuid(get_field(metadata, "organization_id")),
            external_customer_id=_id(get_field(invoice, "customer")),
            external_subscription_id=sub_id,
            **base,
        )

    def _mandate_event(self, mandate: Any, base: dict[str, Any]) -> BillingEvent:
        """``mandate.updated`` (e.g. a Pix Automático mandate revoked in the bank app): refetch the subscription it
        pays for when it can be resolved (payment method -> customer -> subscription), otherwise flag it for staff."""
        logger.warning("stripe mandate %s updated: status=%s", get_field(mandate, "id"), get_field(mandate, "status"))
        payment_method = get_field(mandate, "payment_method")
        pm_id = _id(payment_method)
        if payment_method is not None and not isinstance(payment_method, str):
            customer = _id(get_field(payment_method, "customer"))
        elif pm_id:
            customer = _id(get_field(self.client.v1.payment_methods.retrieve(pm_id), "customer"))
        else:
            customer = None
        if not customer:  # detached payment method: nothing to refetch
            return BillingEvent(type=EVENT_RISK_FLAGGED, **base)
        page = self.client.v1.subscriptions.list(params={"customer": customer, "status": "all", "limit": 10})
        subs = list(get_field(page, "data") or [])
        match = next((sub for sub in subs if pm_id and _id(get_field(sub, "default_payment_method")) == pm_id), None)
        match = match or next(
            (sub for sub in subs if get_field(sub, "status") not in ENDED_SUBSCRIPTION_STATUSES), None)
        if match is None:
            return BillingEvent(type=EVENT_RISK_FLAGGED, external_customer_id=customer, **base)
        return self._subscription_event(EVENT_SUBSCRIPTION_UPSERTED, get_field(match, "id"), base)

    def _risk_customer(self, event_type: str, obj: Any) -> str | None:
        """Customer behind a refund/dispute/fraud warning; the service logs it for staff review (no access change)."""
        if event_type == "charge.refunded":
            return _id(get_field(obj, "customer"))
        charge = get_field(obj, "charge")
        if charge is not None and not isinstance(charge, str):
            return _id(get_field(charge, "customer"))
        if not charge:
            return None
        return _id(get_field(self.client.v1.charges.retrieve(charge), "customer"))
