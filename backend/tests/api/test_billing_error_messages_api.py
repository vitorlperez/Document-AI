# ruff: noqa: F811
"""Billing error codes keep their machine-readable code/status and answer in pt-BR; billing state exposes the customer."""

import pytest

from app.api.billing import USER_MESSAGES
from app.billing.provider import CheckoutSession, PortalSession
from app.entitlements.errors import EntitlementError
from tests.api.test_account_types_api import create_org, login, set_org
from tests.api.test_auth_and_invitations import auth_api  # noqa: F401

# code -> HTTP status the adapter gives it (docs/stripe-integration-plan.md §6)
RAISED = {
    "pix_mandate_reauth_required": 409,
    "invalid_seats": 422,
    "invalid_promotion_code": 422,
    "plan_unavailable": 503,
    "payment_failed": 402,
    "subscription_required": 409,
}


class RaisingProvider:
    name = "fake"
    configured = True

    def __init__(self) -> None:
        self.error: EntitlementError | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_checkout(self, request):
        self._maybe_raise()
        return CheckoutSession(url="https://pay.example.test/c/1", external_customer_id="cus_1")

    def open_portal(self, request):
        self._maybe_raise()
        return PortalSession(url="https://pay.example.test/portal")

    def change_plan(self, *, subscription, plan_key, interval, seats):
        self._maybe_raise()

    def cancel(self, *, subscription, at_period_end=True):
        self._maybe_raise()

    def parse_webhook(self, *, body, headers):
        raise NotImplementedError

    def list_invoices(self, customer_id, limit=12):
        return []


@pytest.fixture()
def api(auth_api):
    client, factory, gateway, _ = auth_api
    provider = RaisingProvider()
    client.app.state.billing_provider = provider
    login(client, gateway)
    return client, factory, provider


def test_every_new_code_has_a_portuguese_message() -> None:
    assert set(RAISED) <= set(USER_MESSAGES)
    for message in USER_MESSAGES.values():
        assert message.endswith(".") and " " in message  # a sentence, not an echoed code


@pytest.mark.parametrize("code,status", RAISED.items())
def test_provider_errors_are_translated_on_checkout(api, code, status) -> None:
    client, _, provider = api
    org = create_org(client)["id"]
    provider.error = EntitlementError(code, "english provider text", status_code=status)
    response = client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro"})
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["detail"] == USER_MESSAGES[code]


def test_portal_without_customer_says_a_subscription_is_required(api) -> None:
    client, _, provider = api
    org = create_org(client)["id"]
    provider.error = EntitlementError("subscription_required", "no billing customer yet", status_code=409)
    response = client.post(f"/organizations/{org}/billing/portal")
    assert response.status_code == 409 and response.json()["detail"] == USER_MESSAGES["subscription_required"]


def test_change_plan_and_cancel_without_subscription_are_translated(api) -> None:
    client, _, _ = api
    org = create_org(client)["id"]
    for path, payload in (("change-plan", {"plan_key": "personal_pro"}), ("cancel", None)):
        response = client.post(f"/organizations/{org}/billing/{path}", json=payload) if payload else client.post(
            f"/organizations/{org}/billing/{path}")
        assert response.status_code == 409
        assert response.json() == {**response.json(), "code": "subscription_required",
                                   "detail": USER_MESSAGES["subscription_required"]}


def test_invalid_seat_count_from_the_api_layer_is_translated(api) -> None:
    client, _, _ = api
    org = create_org(client)["id"]
    response = client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro", "seats": 3})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_seats" and response.json()["detail"] == USER_MESSAGES["invalid_seats"]


def test_codes_without_a_translation_keep_their_original_text(api) -> None:
    client, _, provider = api
    org = create_org(client)["id"]
    provider.error = EntitlementError("something_else", "original text", status_code=400)
    response = client.post(f"/organizations/{org}/billing/portal")
    assert response.json()["detail"] == "original text"


def test_billing_state_tells_whether_a_provider_customer_exists(api) -> None:
    client, factory, _ = api
    org = create_org(client)["id"]
    assert client.get(f"/organizations/{org}/billing").json()["has_billing_customer"] is False
    set_org(factory, org, billing_provider="fake", billing_customer_id="cus_42")
    state = client.get(f"/organizations/{org}/billing").json()
    assert state["has_billing_customer"] is True
    assert "cus_42" not in str(state)  # the id itself is never exposed


@pytest.mark.parametrize("status,blocked", [("active", True), ("trialing", True), ("past_due", True), ("unpaid", True),
                                            ("paused", True), ("incomplete", False)])
def test_checkout_is_refused_while_a_subscription_is_live(api, status, blocked) -> None:
    from uuid import UUID

    from app.organizations.models import Subscription

    client, factory, _ = api
    org = create_org(client)["id"]
    with factory.begin() as session:
        session.add(Subscription(organization_id=UUID(org), provider="fake", external_subscription_id="sub_1",
                                 plan_key="personal_basic", status=status, seats=1, interval="month"))
    response = client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro"})
    if blocked:
        assert response.status_code == 409 and response.json()["code"] == "subscription_exists"
        assert response.json()["detail"] == USER_MESSAGES["subscription_exists"]
    else:
        assert response.status_code == 200, response.text
