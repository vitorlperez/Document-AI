"""StripeBillingProvider.parse_webhook: locally signed payloads -> normalized BillingEvent (fake client)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest

from app.billing.provider import (
    EVENT_IGNORED,
    EVENT_PAYMENT_FAILED,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_RISK_FLAGGED,
    EVENT_SUBSCRIPTION_CANCELED,
    EVENT_SUBSCRIPTION_UPSERTED,
    WebhookRejected,
)
from app.billing.stripe_provider import SUBSCRIPTION_EXPAND, StripeBillingProvider
from tests.unit.test_stripe_provider import (
    ORG,
    FakeStripeClient,
    make_settings,
    sign,
    subscription_obj,
)

CREATED = 1_800_000_000


def payload(event_type: str, obj: dict, event_id: str = "evt_1", created: int = CREATED) -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": event_type, "created": created,
                       "data": {"object": obj}}).encode()


@pytest.fixture()
def fake() -> FakeStripeClient:
    client = FakeStripeClient()
    client.subscriptions_by_id["sub_1"] = subscription_obj(quantity=7)
    return client


@pytest.fixture()
def provider(fake) -> StripeBillingProvider:
    return StripeBillingProvider(make_settings(), client=fake)


def parse(provider, body: bytes, headers: dict | None = None):
    return provider.parse_webhook(body=body, headers=headers if headers is not None else {"Stripe-Signature": sign(body)})


# -- signature ----------------------------------------------------------------------------------------------------


def test_bad_missing_or_stale_signatures_are_rejected(provider, fake) -> None:
    body = payload("customer.subscription.updated", {"id": "sub_1"})
    with pytest.raises(WebhookRejected):
        parse(provider, body, {})
    with pytest.raises(WebhookRejected):
        parse(provider, body, {"stripe-signature": sign(body, secret="whsec_other")})
    with pytest.raises(WebhookRejected):
        parse(provider, body + b" ", {"stripe-signature": sign(body)})  # tampered body
    with pytest.raises(WebhookRejected):
        parse(provider, body, {"stripe-signature": sign(body, timestamp=int(time.time()) - 3600)})
    with pytest.raises(WebhookRejected):
        parse(provider, b"not json", {"stripe-signature": sign(b"not json")})
    assert fake.calls == []  # nothing fetched before the signature is trusted


def test_no_webhook_secret_rejects(fake) -> None:
    provider = StripeBillingProvider(make_settings(stripe_webhook_secret=None), client=fake)
    body = payload("customer.subscription.updated", {"id": "sub_1"})
    with pytest.raises(WebhookRejected):
        parse(provider, body)


def test_stripe_api_errors_propagate_so_stripe_retries(provider, fake) -> None:
    fake.handlers[("subscriptions", "retrieve")] = RuntimeError("stripe api unavailable")
    with pytest.raises(RuntimeError):
        parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}))


# -- subscription lifecycle ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ["customer.subscription.created", "customer.subscription.updated",
                                        "customer.subscription.paused", "customer.subscription.resumed"])
def test_subscription_events_refetch_and_normalize(provider, fake, event_type) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(
        quantity=7, cancel_at=1_910_000_000, cancel_at_period_end=True, status="trialing")
    event = parse(provider, payload(event_type, {"id": "sub_1", "status": "stale-snapshot"}))
    assert event.type == EVENT_SUBSCRIPTION_UPSERTED
    assert (event.id, event.occurred_at) == ("evt_1", datetime.fromtimestamp(CREATED, UTC))
    assert event.occurred_at.tzinfo is not None
    assert (event.organization_id, event.external_customer_id, event.external_subscription_id) == (ORG, "cus_1", "sub_1")
    assert (event.plan_key, event.interval, event.seats, event.status) == ("business_team", "month", 7, "trialing")
    assert event.current_period_end == datetime.fromtimestamp(1_900_000_000, UTC)  # from items.data[0]
    assert event.cancel_at == datetime.fromtimestamp(1_910_000_000, UTC) and event.cancel_at_period_end is True
    (_, _, (sub_id,), call), = fake.calls_to("subscriptions", "retrieve")
    assert sub_id == "sub_1" and call["params"] == {"expand": SUBSCRIPTION_EXPAND}


def test_deleted_subscription_is_a_cancel(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(status="canceled")
    event = parse(provider, payload("customer.subscription.deleted", {"id": "sub_1"}))
    assert (event.type, event.status, event.external_subscription_id) == (EVENT_SUBSCRIPTION_CANCELED, "canceled", "sub_1")


def test_plan_falls_back_to_product_metadata_and_unknown_plans_stay_none(provider, fake) -> None:
    sub = subscription_obj()
    sub["items"]["data"][0]["price"] = {"id": "price_x", "metadata": {}, "recurring": {"interval": "year"},
                                        "product": {"id": "arquivio_personal_pro", "metadata": {"plan_key": "personal_pro"}}}
    fake.subscriptions_by_id["sub_1"] = sub
    event = parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}))
    assert (event.plan_key, event.interval) == ("personal_pro", "year")
    sub["items"]["data"][0]["price"] = {"id": "price_y", "lookup_key": "business_team_monthly", "metadata": {}}
    event = parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}, event_id="evt_2"))
    assert event.plan_key is None  # lookup keys are never trusted for the plan


def test_discount_summary_and_coupon(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(discounts=[{
        "id": "di_1", "end": 1_850_000_000,
        "source": {"type": "coupon", "coupon": {"id": "LAUNCH", "name": "Lançamento", "percent_off": 20,
                                                "duration": "repeating", "duration_in_months": 3}},
        "promotion_code": {"id": "promo_123", "code": "LANCA20"}}])
    event = parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}))
    assert event.coupon_code == "LANCA20"
    assert event.discount_summary == {
        "coupon_id": "LAUNCH", "promotion_code": "LANCA20", "name": "Lançamento", "percent_off": 20,
        "duration": "repeating", "duration_in_months": 3, "end": datetime.fromtimestamp(1_850_000_000, UTC).isoformat()}
    fake.subscriptions_by_id["sub_1"] = subscription_obj(discounts=[{"id": "di_2", "coupon": {"id": "OLD", "amount_off": 500,
                                                                                               "currency": "brl"}}])
    event = parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}, event_id="evt_2"))
    assert event.coupon_code == "OLD" and event.discount_summary["amount_off"] == 500


def test_metadata_without_a_valid_org_id_leaves_resolution_to_the_customer(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(metadata={"organization_id": "not-a-uuid"})
    event = parse(provider, payload("customer.subscription.updated", {"id": "sub_1"}))
    assert event.organization_id is None and event.external_customer_id == "cus_1"


# -- checkout -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ["checkout.session.completed", "checkout.session.async_payment_succeeded",
                                        "checkout.session.async_payment_failed"])
def test_checkout_events_refetch_the_subscription(provider, fake, event_type) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(status="incomplete", metadata={})
    session = {"id": "cs_1", "object": "checkout.session", "mode": "subscription", "subscription": "sub_1",
               "customer": "cus_1", "client_reference_id": str(ORG), "payment_status": "unpaid"}
    event = parse(provider, payload(event_type, session))
    assert (event.type, event.status) == (EVENT_SUBSCRIPTION_UPSERTED, "incomplete")  # incomplete grants nothing
    assert event.organization_id == ORG  # client_reference_id fallback


def test_non_subscription_checkout_is_ignored(provider, fake) -> None:
    event = parse(provider, payload("checkout.session.completed", {"id": "cs_1", "mode": "payment", "customer": "cus_1"}))
    assert event.type == EVENT_IGNORED and fake.calls == []


# -- invoices -----------------------------------------------------------------------------------------------------


def invoice(**fields) -> dict:
    return {"id": "in_1", "object": "invoice", "customer": "cus_1",
            "parent": {"type": "subscription_details",
                       "subscription_details": {"subscription": "sub_1", "metadata": {"organization_id": str(ORG)}}}} | fields


@pytest.mark.parametrize(("event_type", "kind"), [("invoice.paid", EVENT_PAYMENT_SUCCEEDED),
                                                  ("invoice.payment_failed", EVENT_PAYMENT_FAILED)])
def test_invoice_payment_events(provider, fake, event_type, kind) -> None:
    event = parse(provider, payload(event_type, invoice()))
    assert (event.type, event.external_subscription_id, event.external_customer_id, event.organization_id) == (
        kind, "sub_1", "cus_1", ORG)
    assert fake.calls == []  # payment events need no refetch


def test_invoice_subscription_legacy_field(provider) -> None:
    event = parse(provider, payload("invoice.paid", {"id": "in_1", "customer": "cus_1", "subscription": "sub_9"}))
    assert event.external_subscription_id == "sub_9" and event.organization_id is None


def test_payment_action_required_refetches(provider, fake) -> None:
    fake.subscriptions_by_id["sub_1"] = subscription_obj(status="past_due")
    event = parse(provider, payload("invoice.payment_action_required", invoice()))
    assert (event.type, event.status) == (EVENT_SUBSCRIPTION_UPSERTED, "past_due")
    event = parse(provider, payload("invoice.payment_action_required", invoice(parent=None), event_id="evt_2"))
    assert event.type == EVENT_IGNORED


# -- risk / unknown -----------------------------------------------------------------------------------------------


def test_risk_events_are_flagged_with_their_customer(provider, fake) -> None:
    fake.charges_by_id["ch_1"] = {"id": "ch_1", "customer": "cus_1"}
    refund = parse(provider, payload("charge.refunded", {"id": "ch_1", "object": "charge", "customer": "cus_1"}))
    dispute = parse(provider, payload("charge.dispute.created", {"id": "dp_1", "charge": "ch_1"}, event_id="evt_2"))
    fraud = parse(provider, payload("radar.early_fraud_warning.created", {"id": "issfr_1", "charge": "ch_1"},
                                    event_id="evt_3"))
    for event in (refund, dispute, fraud):
        assert (event.type, event.external_customer_id, event.status) == (EVENT_RISK_FLAGGED, "cus_1", None)
    assert [call[2] for call in fake.calls_to("charges", "retrieve")] == [("ch_1",), ("ch_1",)]


def test_unknown_events_are_ignored_not_rejected(provider, fake) -> None:
    event = parse(provider, payload("customer.updated", {"id": "cus_1", "object": "customer"}))
    assert (event.type, event.external_customer_id) == (EVENT_IGNORED, "cus_1")
    event = parse(provider, payload("product.created", {"id": "prod_1", "object": "product"}, event_id="evt_2"))
    assert (event.type, event.external_customer_id) == (EVENT_IGNORED, None)
    assert fake.calls == []


# -- mandate.updated (Pix Automático revocation) --------------------------------------------------------------------


def test_mandate_update_refetches_the_subscription_paid_by_that_payment_method(provider, fake) -> None:
    fake.payment_methods_by_id["pm_pix"] = {"id": "pm_pix", "type": "pix", "customer": "cus_1"}
    fake.handlers[("subscriptions", "list")] = {"data": [
        {"id": "sub_other", "status": "active", "default_payment_method": "pm_card"},
        {"id": "sub_1", "status": "active", "default_payment_method": "pm_pix"},
    ]}
    event = parse(provider, payload("mandate.updated", {"id": "mandate_1", "object": "mandate", "status": "inactive",
                                                        "payment_method": "pm_pix", "type": "multi_use"}))
    assert event.type == EVENT_SUBSCRIPTION_UPSERTED
    assert (event.external_subscription_id, event.organization_id, event.seats) == ("sub_1", ORG, 7)
    (_, _, _, listing), = fake.calls_to("subscriptions", "list")
    assert listing["params"] == {"customer": "cus_1", "status": "all", "limit": 10}


def test_mandate_update_falls_back_to_the_live_subscription(provider, fake) -> None:
    fake.handlers[("subscriptions", "list")] = {"data": [
        {"id": "sub_old", "status": "canceled"}, {"id": "sub_1", "status": "past_due"}]}
    event = parse(provider, payload("mandate.updated", {
        "id": "mandate_1", "object": "mandate", "payment_method": {"id": "pm_pix", "customer": "cus_1"}}))
    assert (event.type, event.external_subscription_id) == (EVENT_SUBSCRIPTION_UPSERTED, "sub_1")
    assert fake.calls_to("payment_methods", "retrieve") == []  # already expanded


def test_unresolvable_mandate_update_is_flagged_for_staff(provider, fake) -> None:
    fake.payment_methods_by_id["pm_gone"] = {"id": "pm_gone", "customer": None}
    event = parse(provider, payload("mandate.updated", {"id": "mandate_1", "payment_method": "pm_gone"}))
    assert (event.type, event.external_customer_id) == (EVENT_RISK_FLAGGED, None)
    assert fake.calls_to("subscriptions", "list") == []

    fake.payment_methods_by_id["pm_pix"] = {"id": "pm_pix", "customer": "cus_9"}
    event = parse(provider, payload("mandate.updated", {"id": "mandate_2", "payment_method": "pm_pix"}, "evt_2"))
    assert (event.type, event.external_customer_id) == (EVENT_RISK_FLAGGED, "cus_9")
    assert event.id == "evt_2" and event.occurred_at == datetime.fromtimestamp(CREATED, UTC)
