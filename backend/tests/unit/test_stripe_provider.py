"""StripeBillingProvider operations against an in-memory fake ``StripeClient`` (no ``stripe`` package, no network)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.billing.provider import CheckoutRequest, InvoiceSummary, PortalRequest
from app.billing.stripe_catalog import desired_price, lookup_key, max_charge_cents
from app.billing.stripe_provider import StripeBillingProvider
from app.entitlements.errors import BillingNotConfigured, EntitlementError

ORG = UUID("00000000-0000-4000-8000-000000000001")
WEBHOOK_SECRET = "whsec_test_fake_secret"


class SignatureVerificationError(Exception):
    """Same class name as ``stripe.SignatureVerificationError`` (the provider matches by name)."""


class CardError(Exception):
    pass


def sign(payload: bytes, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    """Stripe-Signature header for ``payload`` (``t=<ts>,v1=<hmac-sha256(secret, "<ts>.<payload>")>``)."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


class FakeService:
    def __init__(self, client: FakeStripeClient, name: str) -> None:
        self.client, self.name = client, name

    def _record(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.client.calls.append((self.name, method, args, kwargs))
        handler = self.client.handlers.get((self.name, method))
        if isinstance(handler, Exception):
            raise handler
        return handler(*args, **kwargs) if callable(handler) else handler

    def list(self, params=None, options=None):
        return self._record("list", params=params, options=options)

    def create(self, params=None, options=None):
        return self._record("create", params=params, options=options)

    def retrieve(self, id, params=None, options=None):
        return self._record("retrieve", id, params=params, options=options)

    def update(self, id, params=None, options=None):
        return self._record("update", id, params=params, options=options)

    def cancel(self, id, params=None, options=None):
        return self._record("cancel", id, params=params, options=options)


class FakeStripeClient:
    """Mimics ``stripe.StripeClient``: ``client.v1.<service>`` plus ``construct_event`` with real HMAC checks."""

    def __init__(self, secret: str = WEBHOOK_SECRET) -> None:
        self.secret = secret
        self.calls: list[tuple] = []
        self.subscriptions_by_id: dict[str, dict] = {}
        self.charges_by_id: dict[str, dict] = {}
        self.payment_methods_by_id: dict[str, dict] = {}
        self.handlers: dict[tuple[str, str], Any] = {
            ("prices", "list"): lambda params=None, options=None: {
                "data": [{"id": f"price_{key}"} for key in params["lookup_keys"]]},
            ("promotion_codes", "list"): lambda params=None, options=None: {
                "data": [{"id": "promo_123", "code": params["code"]}] if params["code"] == "LANCA20" else []},
            ("customers", "create"): {"id": "cus_new"},
            ("checkout.sessions", "create"): {"id": "cs_test_1", "url": "https://checkout.stripe.test/cs_test_1"},
            ("billing_portal.sessions", "create"): {"url": "https://billing.stripe.test/p/1"},
            ("subscriptions", "retrieve"): lambda id, params=None, options=None: self.subscriptions_by_id[id],
            ("subscriptions", "update"): lambda id, params=None, options=None: {"id": id},
            ("subscriptions", "cancel"): lambda id, params=None, options=None: {"id": id, "status": "canceled"},
            ("charges", "retrieve"): lambda id, params=None, options=None: self.charges_by_id[id],
            ("invoices", "list"): {"data": []},
            ("payment_methods", "retrieve"): lambda id, params=None, options=None: self.payment_methods_by_id[id],
            ("subscriptions", "list"): {"data": []},
        }
        self.v1 = SimpleNamespace(
            prices=FakeService(self, "prices"),
            promotion_codes=FakeService(self, "promotion_codes"),
            customers=FakeService(self, "customers"),
            checkout=SimpleNamespace(sessions=FakeService(self, "checkout.sessions")),
            billing_portal=SimpleNamespace(sessions=FakeService(self, "billing_portal.sessions")),
            subscriptions=FakeService(self, "subscriptions"),
            charges=FakeService(self, "charges"),
            invoices=FakeService(self, "invoices"),
            payment_methods=FakeService(self, "payment_methods"),
        )

    def construct_event(self, payload, sig_header, secret, tolerance: int = 300):
        payload_bytes = payload if isinstance(payload, bytes) else payload.encode()
        parts = dict(part.split("=", 1) for part in sig_header.split(",") if "=" in part)
        timestamp = int(parts.get("t", "0") or 0)
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts.get("v1", "")) or abs(time.time() - timestamp) > tolerance:
            raise SignatureVerificationError("No signatures found matching the expected signature for payload")
        return json.loads(payload_bytes)  # ValueError on garbage, like the SDK

    def calls_to(self, service: str, method: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == service and call[1] == method]


def make_settings(**overrides):
    values = {
        "stripe_api_key": SecretStr("rk_test_fake"),
        "stripe_webhook_secret": SecretStr(WEBHOOK_SECRET),
        "stripe_api_version": "2026-09-30.endive",
        "stripe_checkout_integration_id": "arquivio_checkout_pnsxiqba",
        "stripe_portal_configuration_id": None,
    }
    return SimpleNamespace(**(values | overrides))


@pytest.fixture()
def fake() -> FakeStripeClient:
    return FakeStripeClient()


@pytest.fixture()
def provider(fake) -> StripeBillingProvider:
    return StripeBillingProvider(make_settings(), client=fake)


def subscription_obj(sub_id: str = "sub_1", *, plan_key: str = "business_team", interval: str = "month", quantity: int = 5,
                     price_id: str = "price_x", item_id: str = "si_1", **fields) -> dict:
    return {
        "id": sub_id, "object": "subscription", "customer": "cus_1", "status": "active",
        "metadata": {"organization_id": str(ORG)}, "cancel_at": None, "cancel_at_period_end": False,
        "discounts": [],
        "items": {"data": [{"id": item_id, "quantity": quantity, "current_period_end": 1_900_000_000,
                            "price": {"id": price_id, "metadata": {"plan_key": plan_key, "interval": interval},
                                      "recurring": {"interval": interval}}}]},
    } | fields


# -- construction -------------------------------------------------------------------------------------------------


def test_a_real_client_needs_an_api_key() -> None:
    with pytest.raises(BillingNotConfigured):
        StripeBillingProvider(make_settings(stripe_api_key=None))


def test_identity(provider) -> None:
    assert (provider.name, provider.configured) == ("stripe", True)


# -- checkout -----------------------------------------------------------------------------------------------------


def test_business_checkout_creates_the_customer_once_and_never_passes_payment_method_types(provider, fake) -> None:
    result = provider.create_checkout(CheckoutRequest(
        organization_id=ORG, plan_key="business_team", interval="month", seats=7, customer_email="dona@acme.co",
        success_url="https://app.test/app/billing?checkout=success", cancel_url="https://app.test/app/billing"))
    assert result.url == "https://checkout.stripe.test/cs_test_1"
    assert (result.external_customer_id, result.external_id) == ("cus_new", "cs_test_1")

    (_, _, _, customer), = fake.calls_to("customers", "create")
    assert customer["options"] == {"idempotency_key": f"org-{ORG}-customer"}
    assert customer["params"]["metadata"] == {"organization_id": str(ORG)}
    assert customer["params"]["preferred_locales"] == ["pt-BR"] and customer["params"]["email"] == "dona@acme.co"

    (_, _, _, prices), = fake.calls_to("prices", "list")
    assert prices["params"]["lookup_keys"] == [lookup_key("business_team", "month")]

    (_, _, _, session), = fake.calls_to("checkout.sessions", "create")
    params = session["params"]
    assert params["mode"] == "subscription" and params["customer"] == "cus_new"
    assert params["line_items"] == [{"price": "price_business_team_monthly", "quantity": 7}]
    assert params["client_reference_id"] == str(ORG)
    assert params["subscription_data"]["metadata"] == {
        "organization_id": str(ORG), "plan_key": "business_team", "interval": "month"}
    assert params["locale"] == "pt-BR"
    assert params["integration_identifier"] == "arquivio_checkout_pnsxiqba"
    assert params["success_url"].endswith("checkout=success") and params["cancel_url"].endswith("/app/billing")
    assert params["billing_address_collection"] == "required" and params["tax_id_collection"] == {"enabled": True}
    assert params["customer_update"] == {"name": "auto", "address": "auto"}
    assert params["allow_promotion_codes"] is True and "discounts" not in params
    assert "payment_method_types" not in params and "automatic_tax" not in params


def test_personal_checkout_reuses_the_customer_and_applies_a_promotion_code(provider, fake) -> None:
    provider.create_checkout(CheckoutRequest(
        organization_id=ORG, plan_key="personal_pro", interval="year", seats=1, external_customer_id="cus_old",
        promotion_code="LANCA20"))
    assert fake.calls_to("customers", "create") == []
    (_, _, _, session), = fake.calls_to("checkout.sessions", "create")
    params = session["params"]
    assert params["customer"] == "cus_old"
    assert params["line_items"] == [{"price": "price_personal_pro_yearly", "quantity": 1}]
    assert params["discounts"] == [{"promotion_code": "promo_123"}] and "allow_promotion_codes" not in params
    assert "tax_id_collection" not in params and "billing_address_collection" not in params


def test_unknown_promotion_code_is_a_422_before_any_session(provider, fake) -> None:
    with pytest.raises(EntitlementError) as error:
        provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="personal_pro", interval="month",
                                                 seats=1, external_customer_id="cus_old", promotion_code="NOPE"))
    assert (error.value.code, error.value.status_code) == ("invalid_promotion_code", 422)
    assert fake.calls_to("checkout.sessions", "create") == []


def test_missing_price_is_reported_not_guessed(provider, fake) -> None:
    fake.handlers[("prices", "list")] = {"data": []}
    with pytest.raises(EntitlementError) as error:
        provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="personal_pro", interval="month", seats=1))
    assert (error.value.code, error.value.status_code) == ("plan_unavailable", 503)
    assert fake.calls_to("customers", "create") == []


def test_price_lookup_is_cached_in_process(provider, fake) -> None:
    for _ in range(3):
        provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="personal_pro", interval="month",
                                                 seats=1, external_customer_id="cus_old"))
    assert len(fake.calls_to("prices", "list")) == 1


# -- portal -------------------------------------------------------------------------------------------------------


def test_portal_uses_the_configured_portal_configuration(fake) -> None:
    provider = StripeBillingProvider(make_settings(stripe_portal_configuration_id="bpc_123"), client=fake)
    session = provider.open_portal(PortalRequest(organization_id=ORG, external_customer_id="cus_1",
                                                 return_url="https://app.test/app/billing"))
    assert session.url == "https://billing.stripe.test/p/1"
    (_, _, _, call), = fake.calls_to("billing_portal.sessions", "create")
    assert call["params"] == {"customer": "cus_1", "locale": "pt-BR", "return_url": "https://app.test/app/billing",
                              "configuration": "bpc_123"}


def test_portal_without_configuration_or_customer(provider, fake) -> None:
    provider.open_portal(PortalRequest(organization_id=ORG, external_customer_id="cus_1"))
    (_, _, _, call), = fake.calls_to("billing_portal.sessions", "create")
    assert "configuration" not in call["params"]
    with pytest.raises(EntitlementError) as error:
        provider.open_portal(PortalRequest(organization_id=ORG, external_customer_id=None))
    assert error.value.status_code == 409


# -- change plan / cancel -----------------------------------------------------------------------------------------


def local_sub(**fields):
    return SimpleNamespace(**({"external_subscription_id": "sub_1", "plan_key": "business_team", "interval": "month",
                               "seats": 5} | fields))


def test_upgrade_invoices_now_and_fails_hard_on_incomplete_payment(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(quantity=5)
    provider.change_plan(subscription=local_sub(), plan_key="business_team", interval="month", seats=8)
    (_, _, (sub_id,), call), = fake.calls_to("subscriptions", "update")
    assert sub_id == "sub_1"
    params = call["params"]
    assert params["items"] == [{"id": "si_1", "price": "price_business_team_monthly", "quantity": 8}]
    assert params["proration_behavior"] == "always_invoice"
    assert params["payment_behavior"] == "error_if_incomplete"
    assert call["options"]["idempotency_key"].startswith("arquivio-change-sub_1-")


def test_downgrade_creates_prorations_for_the_next_invoice(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(plan_key="business_scale", quantity=20)
    provider.change_plan(subscription=local_sub(plan_key="business_scale", seats=20), plan_key="business_team",
                         interval="month", seats=6)
    (_, _, _, call), = fake.calls_to("subscriptions", "update")
    assert call["params"]["proration_behavior"] == "create_prorations"


def test_change_plan_raises_before_the_caller_writes(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(quantity=5)
    fake.handlers[("subscriptions", "update")] = CardError("Your card was declined.")
    with pytest.raises(EntitlementError) as error:
        provider.change_plan(subscription=local_sub(), plan_key="business_team", interval="month", seats=9)
    assert (error.value.code, error.value.status_code) == ("payment_failed", 402)
    fake.handlers[("subscriptions", "update")] = RuntimeError("api down")
    with pytest.raises(RuntimeError):
        provider.change_plan(subscription=local_sub(), plan_key="business_team", interval="month", seats=9)


def test_cancel_at_period_end_or_now(provider, fake) -> None:
    provider.cancel(subscription=local_sub())
    (_, _, (sub_id,), call), = fake.calls_to("subscriptions", "update")
    assert sub_id == "sub_1" and call["params"] == {"cancel_at_period_end": True}
    provider.cancel(subscription=local_sub(), at_period_end=False)
    assert [call[2] for call in fake.calls_to("subscriptions", "cancel")] == [("sub_1",)]


# -- invoices -----------------------------------------------------------------------------------------------------


def test_list_invoices_normalizes_and_skips_drafts(provider, fake) -> None:
    fake.handlers[("invoices", "list")] = {"data": [
        {"id": "in_1", "number": "ARQ-0001", "status": "paid", "total": 4990, "currency": "BRL", "created": 1_800_000_000,
         "hosted_invoice_url": "https://invoice.stripe.test/i/1", "invoice_pdf": "https://invoice.stripe.test/i/1.pdf"},
        {"id": "in_draft", "number": None, "status": "draft", "total": 4990, "currency": "brl", "created": 1_800_000_100},
    ]}
    invoices = provider.list_invoices("cus_1", limit=500)
    assert invoices == [InvoiceSummary(
        id="in_1", number="ARQ-0001", status="paid", total=4990, currency="brl",
        created=datetime.fromtimestamp(1_800_000_000, UTC), hosted_invoice_url="https://invoice.stripe.test/i/1",
        invoice_pdf="https://invoice.stripe.test/i/1.pdf")]
    assert invoices[0].created.tzinfo is not None
    (_, _, _, call), = fake.calls_to("invoices", "list")
    assert call["params"] == {"customer": "cus_1", "limit": 100}
    assert provider.list_invoices("") == []


# -- wave 3: billing_mode, seat guard, tax ID, Pix Automático ------------------------------------------------------


def checkout_params(fake) -> dict:
    (_, _, _, session), = fake.calls_to("checkout.sessions", "create")
    return session["params"]


def test_checkout_pins_flexible_billing_mode_and_the_hosted_default(provider, fake) -> None:
    provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="business_team", interval="month", seats=5,
                                             external_customer_id="cus_old"))
    params = checkout_params(fake)
    assert params["subscription_data"]["billing_mode"] == {"type": "flexible"}
    assert "ui_mode" not in params and "hosted" not in json.dumps(params)
    # Tax IDs: best effort for business, never required; no automatic tax at all (unsupported for BR accounts).
    assert params["tax_id_collection"].get("required", "never") == "never"
    assert "automatic_tax" not in params and "automatic_tax" not in params["subscription_data"]
    assert "payment_method_options" not in params  # Pix off by default


@pytest.mark.parametrize("seats", [0, -1, None])
def test_checkout_rejects_fewer_than_one_seat_before_any_call(provider, fake, seats) -> None:
    with pytest.raises(EntitlementError) as error:
        provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="business_team", interval="month",
                                                 seats=seats))
    assert (error.value.code, error.value.status_code) == ("invalid_seats", 422)
    assert fake.calls == []


@pytest.mark.parametrize("seats", [0, -3])
def test_change_plan_rejects_fewer_than_one_seat_before_any_call(provider, fake, seats) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj()
    with pytest.raises(EntitlementError) as error:
        provider.change_plan(subscription=local_sub(), plan_key="business_team", interval="month", seats=seats)
    assert error.value.code == "invalid_seats"
    assert fake.calls == []


@pytest.fixture()
def pix_provider(fake) -> StripeBillingProvider:
    return StripeBillingProvider(make_settings(stripe_pix_enabled=True), client=fake)


@pytest.mark.parametrize(("interval", "schedule"), [("month", "monthly"), ("year", "yearly")])
def test_pix_checkout_sets_a_maximum_mandate_covering_max_seats(pix_provider, fake, interval, schedule) -> None:
    pix_provider.create_checkout(CheckoutRequest(organization_id=ORG, plan_key="business_team", interval=interval,
                                                 seats=5, external_customer_id="cus_old"))
    mandate = checkout_params(fake)["payment_method_options"]["pix"]["mandate_options"]
    assert mandate == {"amount": max_charge_cents("business_team", interval), "amount_type": "maximum",
                       "currency": "brl", "payment_schedule": schedule, "reference": "Arquivio business_team"}
    assert mandate["amount"] == desired_price("business_team", interval).total_cents(15)  # max_seats, not 5
    assert "payment_method_types" not in checkout_params(fake)


def pix_sub(**fields) -> dict:
    return subscription_obj(quantity=5, default_payment_method={"id": "pm_pix", "type": "pix"}) | fields


def test_pix_change_within_the_mandate_goes_through(pix_provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = pix_sub()
    pix_provider.change_plan(subscription=local_sub(), plan_key="business_team", interval="month", seats=15)
    (_, _, _, retrieve), = fake.calls_to("subscriptions", "retrieve")
    assert "default_payment_method" in retrieve["params"]["expand"]
    assert len(fake.calls_to("subscriptions", "update")) == 1


@pytest.mark.parametrize(("plan_key", "interval"), [("business_scale", "month"), ("business_team", "year")])
def test_pix_change_beyond_the_mandate_needs_reauthorization(pix_provider, fake, plan_key, interval) -> None:
    fake.subscriptions_by_id["sub_1"] = pix_sub()
    with pytest.raises(EntitlementError) as error:
        pix_provider.change_plan(subscription=local_sub(), plan_key=plan_key, interval=interval, seats=20)
    assert (error.value.code, error.value.status_code) == ("pix_mandate_reauth_required", 409)
    assert fake.calls_to("subscriptions", "update") == []


def test_pix_yearly_mandate_cannot_switch_to_monthly(pix_provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(
        interval="year", quantity=5, default_payment_method="pm_pix")
    fake.payment_methods_by_id["pm_pix"] = {"id": "pm_pix", "type": "pix"}
    with pytest.raises(EntitlementError) as error:
        pix_provider.change_plan(subscription=local_sub(interval="year"), plan_key="business_team", interval="month",
                                 seats=5)
    assert error.value.code == "pix_mandate_reauth_required"
    assert [call[2] for call in fake.calls_to("payment_methods", "retrieve")] == [("pm_pix",)]


def test_card_subscriptions_and_pix_off_skip_the_mandate_check(pix_provider, provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(
        quantity=5, default_payment_method={"id": "pm_card", "type": "card"})
    pix_provider.change_plan(subscription=local_sub(), plan_key="business_scale", interval="month", seats=20)
    fake.subscriptions_by_id["sub_1"] = pix_sub()
    provider.change_plan(subscription=local_sub(), plan_key="business_scale", interval="month", seats=20)
    assert len(fake.calls_to("subscriptions", "update")) == 2
    assert fake.calls_to("subscriptions", "retrieve")[-1][3]["params"] == {"expand": ["items.data.price"]}
