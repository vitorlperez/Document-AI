# ruff: noqa: F811
"""GET /organizations/{id}/billing/invoices: owner-only, 501 without a provider, [] before checkout."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.billing.provider import CheckoutSession, InvoiceSummary, NoBillingProvider, PortalSession
from app.entitlements.errors import BillingNotConfigured
from app.identity.models import User
from app.organizations.models import MembershipRole
from tests.api.test_account_types_api import create_org, login, set_org
from tests.api.test_auth_and_invitations import auth_api, make_membership  # noqa: F401

CREATED = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


class InvoiceProvider:
    name = "fake"
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.checkout_requests: list = []

    def create_checkout(self, request):
        self.checkout_requests.append(request)
        return CheckoutSession(url="https://pay.example.test/c/1", external_customer_id="cus_1")

    def open_portal(self, request):
        self.checkout_requests.append(request)
        return PortalSession(url="https://pay.example.test/portal")

    def change_plan(self, *, subscription, plan_key, interval, seats):
        return None

    def cancel(self, *, subscription, at_period_end=True):
        return None

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]):
        raise NotImplementedError

    def list_invoices(self, customer_id: str, limit: int = 12) -> list[InvoiceSummary]:
        self.calls.append(("list_invoices", customer_id, limit))
        return [InvoiceSummary(id="in_1", number="ARQ-0001", status="paid", total=4990, currency="brl", created=CREATED,
                               hosted_invoice_url="https://pay.example.test/i/in_1",
                               invoice_pdf="https://pay.example.test/i/in_1.pdf")]


@pytest.fixture()
def invoice_api(auth_api):
    client, factory, gateway, _ = auth_api
    provider = InvoiceProvider()
    client.app.state.billing_provider = provider
    return client, factory, gateway, provider


def test_invoices_are_501_without_a_provider(auth_api) -> None:
    client, _, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client)["id"]
    response = client.get(f"/organizations/{org}/billing/invoices")
    assert response.status_code == 501 and response.json()["code"] == "billing_not_configured"


def test_no_billing_provider_list_invoices_raises() -> None:
    with pytest.raises(BillingNotConfigured):
        NoBillingProvider().list_invoices("cus_1")


def test_invoices_empty_before_first_checkout(invoice_api) -> None:
    client, _, gateway, provider = invoice_api
    login(client, gateway)
    org = create_org(client)["id"]
    response = client.get(f"/organizations/{org}/billing/invoices")
    assert response.status_code == 200 and response.json() == []
    assert provider.calls == []


def test_invoices_listed_for_the_owner(invoice_api) -> None:
    client, factory, gateway, provider = invoice_api
    login(client, gateway)
    org = create_org(client)["id"]
    set_org(factory, org, billing_provider="fake", billing_customer_id="cus_42")
    response = client.get(f"/organizations/{org}/billing/invoices")
    assert response.status_code == 200
    assert response.json() == [{
        "id": "in_1", "number": "ARQ-0001", "status": "paid", "total": 4990, "currency": "brl",
        "created": "2026-10-01T12:30:00+00:00", "hosted_invoice_url": "https://pay.example.test/i/in_1",
        "invoice_pdf": "https://pay.example.test/i/in_1.pdf"}]
    assert provider.calls == [("list_invoices", "cus_42", 12)]


def test_invoices_require_the_owner(invoice_api) -> None:
    client, factory, gateway, provider = invoice_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    set_org(factory, org, billing_customer_id="cus_42")
    login(client, gateway, "outsider")
    assert client.get(f"/organizations/{org}/billing/invoices").status_code == 403
    login(client, gateway, "admin")
    with factory() as session:
        admin_id = session.scalar(select(User.id).where(User.email == "admin@example.test"))
    make_membership(factory, organization_id=UUID(org), user_id=admin_id, role=MembershipRole.ADMIN)
    assert client.get(f"/organizations/{org}/billing").status_code == 200  # members still read the plan state
    assert client.get(f"/organizations/{org}/billing/invoices").status_code == 403
    assert provider.calls == []


def test_checkout_return_urls_point_at_the_plan_section(invoice_api) -> None:
    client, _, gateway, provider = invoice_api
    login(client, gateway)
    org = create_org(client)["id"]
    assert client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro"}).status_code == 200
    request = provider.checkout_requests[-1]
    assert request.success_url.endswith(f"/companies/{org}/admin?checkout=success")
    assert request.cancel_url.endswith(f"/companies/{org}/admin?checkout=canceled")
    assert client.post(f"/organizations/{org}/billing/portal").status_code == 200
    assert provider.checkout_requests[-1].return_url.endswith(f"/companies/{org}/admin?billing=portal")
