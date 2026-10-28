# ruff: noqa: F811
"""POST /webhooks/billing/stripe end to end: signed raw body -> StripeBillingProvider (fake client) -> BillingService."""

from __future__ import annotations

import json
import time
from uuid import UUID

import pytest
from sqlalchemy import select

from app.billing.stripe_provider import StripeBillingProvider
from app.organizations.models import BillingEvent as BillingEventRow
from app.organizations.models import Organization, Subscription
from tests.api.test_account_types_api import create_org, login
from tests.api.test_auth_and_invitations import auth_api  # noqa: F401
from tests.unit.test_stripe_provider import FakeStripeClient, make_settings, sign, subscription_obj


@pytest.fixture()
def stripe_api(auth_api):
    client, factory, gateway, _ = auth_api
    fake = FakeStripeClient()
    client.app.state.billing_provider = StripeBillingProvider(make_settings(), client=fake)
    return client, factory, gateway, fake


def post(client, event_type: str, obj: dict, event_id: str, *, created: int | None = None, signature: str | None = None):
    body = json.dumps({"id": event_id, "object": "event", "type": event_type, "created": created or int(time.time()),
                       "data": {"object": obj}}, separators=(",", ":")).encode()
    headers = {"content-type": "application/json", "stripe-signature": signature or sign(body)}
    return client.post("/webhooks/billing/stripe", content=body, headers=headers)


def test_signed_stripe_webhook_updates_the_subscription_and_the_plan(stripe_api) -> None:
    client, factory, gateway, fake = stripe_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    fake.subscriptions_by_id["sub_1"] = subscription_obj(metadata={"organization_id": org}, quantity=7)

    response = post(client, "customer.subscription.created", {"id": "sub_1"}, "evt_created")
    assert response.status_code == 200 and response.json() == {"status": "processed"}
    with factory() as session:
        sub = session.scalar(select(Subscription).where(Subscription.external_subscription_id == "sub_1"))
        assert (sub.provider, sub.plan_key, sub.interval, sub.seats, sub.status) == (
            "stripe", "business_team", "month", 7, "active")
        assert sub.current_period_end is not None and sub.external_customer_id == "cus_1"
        organization = session.get(Organization, UUID(org))
        assert (organization.billing_provider, organization.billing_customer_id) == ("stripe", "cus_1")
        assert session.get(BillingEventRow, "stripe:evt_created").processed_at is not None
    state = client.get(f"/organizations/{org}/billing").json()
    assert (state["entitlement_source"], state["plan_key"], state["entitlements"]["max_members"]) == (
        "subscription", "business_team", 7)

    duplicate = post(client, "customer.subscription.created", {"id": "sub_1"}, "evt_created")
    assert duplicate.status_code == 200 and duplicate.json() == {"status": "duplicate"}


def test_bad_signature_is_a_400_and_writes_nothing(stripe_api) -> None:
    client, factory, _, fake = stripe_api
    response = post(client, "customer.subscription.updated", {"id": "sub_1"}, "evt_forged", signature="t=1,v1=deadbeef")
    assert response.status_code == 400
    response = client.post("/webhooks/billing/stripe", content=b"{}", headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert fake.calls == []
    with factory() as session:
        assert session.scalars(select(BillingEventRow)).all() == []


def test_unknown_events_are_acknowledged_and_recorded(stripe_api) -> None:
    client, factory, *_ = stripe_api
    response = post(client, "product.updated", {"id": "prod_1", "object": "product"}, "evt_product")
    assert response.status_code == 200 and response.json() == {"status": "ignored"}
    with factory() as session:
        row = session.get(BillingEventRow, "stripe:evt_product")
        assert row is not None and row.type == "ignored"


def test_the_route_name_must_match_the_configured_provider(stripe_api) -> None:
    client, *_ = stripe_api
    assert client.post("/webhooks/billing/fake", content=b"{}").status_code == 501


def test_metadata_cannot_move_an_organization_onto_another_customer(stripe_api) -> None:
    """A subscription from an unknown customer that merely claims the org id in its metadata is ledger-only."""
    client, factory, gateway, fake = stripe_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    fake.subscriptions_by_id["sub_1"] = subscription_obj(metadata={"organization_id": org})
    assert post(client, "customer.subscription.created", {"id": "sub_1"}, "evt_real").json() == {"status": "processed"}

    fake.subscriptions_by_id["sub_evil"] = subscription_obj(
        sub_id="sub_evil", metadata={"organization_id": org}, customer="cus_evil")
    response = post(client, "customer.subscription.created", {"id": "sub_evil"}, "evt_evil")
    assert response.status_code == 200 and response.json() == {"status": "ignored"}
    with factory() as session:
        assert session.get(Organization, UUID(org)).billing_customer_id == "cus_1"
        assert session.scalar(select(Subscription).where(Subscription.external_subscription_id == "sub_evil")) is None


def test_oversized_webhook_bodies_are_refused_before_verification(stripe_api) -> None:
    client, _, _, fake = stripe_api
    big = b"x" * 1_000_001
    response = client.post("/webhooks/billing/stripe", content=big,
                           headers={"content-type": "application/json", "stripe-signature": "t=1,v1=aa"})
    assert response.status_code == 413
    assert fake.calls == []
