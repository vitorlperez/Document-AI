"""The adapter against the REAL ``stripe.StripeClient`` (SDK v16), never a fake client.

Three layers, none of them reaching api.stripe.com:

* a recording ``HTTPClient`` returns canned JSON, so the real SDK encodes the requests (form bodies, headers) and
  parses real ``StripeObject`` responses and signed webhook events;
* every params dict the code sends is checked recursively against the SDK's own ``TypedDict`` definitions, which
  catches a mistyped (even nested) parameter name offline;
* optionally (``STRIPE_MOCK_URL``, default ``http://localhost:12111``) the same calls run against ``stripe-mock``,
  which validates them against Stripe's OpenAPI spec. Skipped when the mock is not listening.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import sys
import time
import types
import typing
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlparse
from uuid import UUID

import pytest
from pydantic import SecretStr
from typing_extensions import is_typeddict  # the SDK's TypedDicts come from typing_extensions

stripe = pytest.importorskip("stripe")

from stripe.params import (
    InvoiceListParams,
    PriceCreateParams,
    PriceListParams,
    ProductCreateParams,
    PromotionCodeListParams,
    SubscriptionRetrieveParams,
    SubscriptionUpdateParams,
)
from stripe.params.billing_portal import ConfigurationCreateParams
from stripe.params.billing_portal import SessionCreateParams as PortalSessionCreateParams
from stripe.params.checkout import SessionCreateParams as CheckoutSessionCreateParams

from app.billing.provider import (
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_RISK_FLAGGED,
    EVENT_SUBSCRIPTION_UPSERTED,
    CheckoutRequest,
    PortalRequest,
    WebhookRejected,
)
from app.billing.stripe_catalog import (
    desired_portal_configuration,
    desired_prices,
    desired_products,
    get_field,
)
from app.billing.stripe_provider import StripeBillingProvider
from app.entitlements.errors import EntitlementError

ORG = UUID("00000000-0000-4000-8000-000000000001")
WEBHOOK_SECRET = "whsec_contract_secret"
API_VERSION = "2026-09-30.endive"


# -- recording HTTP client -------------------------------------------------------------------------------------------


class RecordedRequest(SimpleNamespace):
    @property
    def form(self) -> dict[str, str]:
        return dict(parse_qsl(self.body or "", keep_blank_values=True)) if self.method != "get" else {}

    @property
    def query(self) -> dict[str, str]:
        return dict(parse_qsl(urlparse(self.url).query, keep_blank_values=True))

    @property
    def path(self) -> str:
        return urlparse(self.url).path


class ReplayHTTPClient(stripe.HTTPClient):
    """Plugs into ``StripeClient(http_client=...)``; answers by ``"<METHOD> <path>"`` with a JSON-able body."""

    name = "replay"

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[RecordedRequest] = []
        self.routes: dict[str, typing.Any] = {}

    def request(self, method, url, headers, post_data=None, *, _usage=None):
        request = RecordedRequest(method=method.lower(), url=url, headers=dict(headers or {}), body=post_data)
        self.requests.append(request)
        key = f"{request.method.upper()} {request.path}"
        if key not in self.routes:
            raise AssertionError(f"unexpected Stripe request: {key}")
        response = self.routes[key]
        status, body = response if isinstance(response, tuple) else (200, response)
        return json.dumps(body), status, {"Request-Id": "req_test"}

    def request_stream(self, *args, **kwargs):  # pragma: no cover - the adapter never streams
        raise NotImplementedError

    def close(self) -> None:
        pass

    def to(self, method: str, path: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method == method.lower() and r.path == path]


def make_settings(**overrides):
    values = {
        "stripe_api_key": SecretStr("rk_test_contract"),
        "stripe_webhook_secret": SecretStr(WEBHOOK_SECRET),
        "stripe_api_version": API_VERSION,
        "stripe_checkout_integration_id": "arquivio_checkout_contract",
        "stripe_portal_configuration_id": None,
        "stripe_pix_enabled": False,
    }
    return SimpleNamespace(**(values | overrides))


def real_client(http: stripe.HTTPClient | None = None, **kwargs) -> stripe.StripeClient:
    return stripe.StripeClient("rk_test_contract", stripe_version=API_VERSION, http_client=http, max_network_retries=0,
                               **kwargs)


@pytest.fixture()
def http() -> ReplayHTTPClient:
    replay = ReplayHTTPClient()
    replay.routes.update({
        "GET /v1/prices": {"object": "list", "has_more": False, "url": "/v1/prices", "data": [
            {"id": "price_biz_m", "object": "price", "lookup_key": "business_team_monthly"}]},
        "POST /v1/customers": {"id": "cus_new", "object": "customer"},
        "POST /v1/checkout/sessions": {"id": "cs_test_1", "object": "checkout.session",
                                       "url": "https://checkout.stripe.com/c/pay/cs_test_1"},
        "GET /v1/promotion_codes": {"object": "list", "has_more": False, "url": "/v1/promotion_codes", "data": [
            {"id": "promo_123", "object": "promotion_code", "code": "LANCA20"}]},
    })
    return replay


@pytest.fixture()
def provider(http) -> StripeBillingProvider:
    return StripeBillingProvider(make_settings(), client=real_client(http))


def checkout(**fields) -> CheckoutRequest:
    values = {"organization_id": ORG, "plan_key": "business_team", "interval": "month", "seats": 5,
              "customer_email": "dono@example.com", "success_url": "https://app.test/ok", "cancel_url": "https://app.test/no"}
    return CheckoutRequest(**(values | fields))


# -- params vs the SDK's TypedDicts ----------------------------------------------------------------------------------


def _resolve(annotation, module):
    if isinstance(annotation, typing.ForwardRef):
        annotation = annotation.__forward_arg__
    if isinstance(annotation, str):
        try:
            return eval(annotation, vars(module))
        except (NameError, SyntaxError, TypeError):
            return None
    return annotation


def _candidates(annotation, module):
    annotation = _resolve(annotation, module)
    if annotation is None:
        return
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType, typing.NotRequired, typing.Required, typing.Annotated):
        for arg in typing.get_args(annotation):
            yield from _candidates(arg, module)
    else:
        yield annotation


def assert_params_match_sdk(params, typed_dict, path="params") -> None:
    """Every key (recursively, through lists and nested TypedDicts) must be a real field of the SDK's params class."""
    module = sys.modules[typed_dict.__module__]
    fields = typed_dict.__annotations__
    for key, value in params.items():
        assert key in fields, f"{path}.{key} is not a field of {typed_dict.__name__}"
        for candidate in _candidates(fields[key], module):
            if is_typeddict(candidate) and isinstance(value, dict):
                assert_params_match_sdk(value, candidate, f"{path}.{key}")
                break
            if typing.get_origin(candidate) in (list, typing.List) and isinstance(value, list):  # noqa: UP006
                item_types = [c for c in _candidates(typing.get_args(candidate)[0], module) if is_typeddict(c)]
                for index, item in enumerate(value):
                    if isinstance(item, dict) and item_types:
                        assert_params_match_sdk(item, item_types[0], f"{path}.{key}[{index}]")
                break


def decode_form(form: dict[str, str]) -> dict:
    """Rebuild the nested dict from Stripe's ``a[b][0][c]=v`` form encoding."""
    root: dict = {}
    for key, value in form.items():
        parts = [p for p in key.replace("]", "").split("[")]
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return root


def test_sdk_pin_matches_pinned_api_version():
    assert stripe.VERSION.startswith("16.")
    assert stripe._api_version._ApiVersion.CURRENT == API_VERSION


def test_checkout_params_are_real_sdk_fields(http):
    for pix, promo in ((False, None), (True, "LANCA20"), (True, "promo_abc")):
        sent = StripeBillingProvider(make_settings(stripe_pix_enabled=pix), client=real_client(http))
        http.requests.clear()
        sent.create_checkout(checkout(promotion_code=promo, external_customer_id="cus_1"))
        form = decode_form(http.to("post", "/v1/checkout/sessions")[0].form)
        assert_params_match_sdk(form, CheckoutSessionCreateParams)


def test_sync_script_params_are_real_sdk_fields():
    for spec in desired_products():
        assert_params_match_sdk(spec.create_params(), ProductCreateParams)
    for spec in desired_prices():
        assert_params_match_sdk(spec.create_params(), PriceCreateParams)
        assert_params_match_sdk({**spec.create_params(), "transfer_lookup_key": True}, PriceCreateParams)
    assert_params_match_sdk(desired_portal_configuration(), ConfigurationCreateParams)
    assert_params_match_sdk({"expand": ["data.tiers"], "lookup_keys": ["a"], "limit": 100}, PriceListParams)
    assert_params_match_sdk({"code": "X", "active": True, "limit": 1}, PromotionCodeListParams)
    assert_params_match_sdk({"customer": "cus_1", "limit": 12}, InvoiceListParams)
    assert_params_match_sdk({"expand": ["items.data.price.product", "discounts.promotion_code"]},
                            SubscriptionRetrieveParams)
    assert_params_match_sdk({"customer": "cus_1", "locale": "pt-BR", "return_url": "https://x", "configuration": "bpc_1"},
                            PortalSessionCreateParams)


# -- request encoding by the real SDK --------------------------------------------------------------------------------


def test_checkout_request_as_sent_on_the_wire(provider, http):
    result = provider.create_checkout(checkout(promotion_code=None))
    assert result.url.startswith("https://checkout.stripe.com/")
    assert result.external_customer_id == "cus_new"

    price_list = http.to("get", "/v1/prices")[0]
    assert price_list.query["lookup_keys[0]"] == "business_team_monthly"
    assert price_list.query["active"] == "true"

    customer = http.to("post", "/v1/customers")[0]
    assert customer.headers["Idempotency-Key"] == f"org-{ORG}-customer"
    assert customer.form["metadata[organization_id]"] == str(ORG)

    session = http.to("post", "/v1/checkout/sessions")[0]
    assert session.headers["Stripe-Version"] == API_VERSION
    assert session.headers["Authorization"] == "Bearer rk_test_contract"
    form = session.form
    assert form["mode"] == "subscription"
    assert form["line_items[0][price]"] == "price_biz_m"
    assert form["line_items[0][quantity]"] == "5"
    assert form["subscription_data[billing_mode][type]"] == "flexible"
    assert form["integration_identifier"] == "arquivio_checkout_contract"
    assert form["client_reference_id"] == str(ORG)
    assert form["locale"] == "pt-BR"
    assert form["allow_promotion_codes"] == "true"
    assert form["tax_id_collection[enabled]"] == "true"
    assert form["billing_address_collection"] == "required"
    assert not [key for key in form if key.startswith(("payment_method_types", "automatic_tax", "ui_mode", "discounts"))]
    assert "payment_method_options[pix][mandate_options][amount]" not in form


def test_promotion_code_text_is_resolved_and_discounts_replace_allow_promotion_codes(provider, http):
    provider.create_checkout(checkout(promotion_code="LANCA20"))
    assert http.to("get", "/v1/promotion_codes")[0].query["code"] == "LANCA20"
    form = http.to("post", "/v1/checkout/sessions")[0].form
    assert form["discounts[0][promotion_code]"] == "promo_123"
    assert "allow_promotion_codes" not in form


def test_pix_mandate_options_on_the_wire(http):
    provider = StripeBillingProvider(make_settings(stripe_pix_enabled=True), client=real_client(http))
    provider.create_checkout(checkout(external_customer_id="cus_1"))
    form = http.to("post", "/v1/checkout/sessions")[0].form
    prefix = "payment_method_options[pix][mandate_options]"
    assert form[f"{prefix}[amount_type]"] == "maximum"
    assert form[f"{prefix}[currency]"] == "brl"
    assert form[f"{prefix}[payment_schedule]"] == "monthly"
    assert int(form[f"{prefix}[amount]"]) > 0


def test_missing_price_is_plan_unavailable(provider, http):
    http.routes["GET /v1/prices"] = {"object": "list", "has_more": False, "url": "/v1/prices", "data": []}
    with pytest.raises(EntitlementError) as error:
        provider.create_checkout(checkout())
    assert error.value.code == "plan_unavailable" and error.value.status_code == 503
    assert not http.to("post", "/v1/checkout/sessions")


def test_portal_request(provider, http):
    http.routes["POST /v1/billing_portal/sessions"] = {"id": "bps_1", "object": "billing_portal.session",
                                                       "url": "https://billing.stripe.com/p/session/x"}
    session = provider.open_portal(PortalRequest(organization_id=ORG, external_customer_id="cus_1",
                                                 return_url="https://app.test/back"))
    assert session.url.startswith("https://billing.stripe.com/")
    form = http.to("post", "/v1/billing_portal/sessions")[0].form
    assert form == {"customer": "cus_1", "locale": "pt-BR", "return_url": "https://app.test/back"}


# -- subscription refetch with real StripeObjects --------------------------------------------------------------------


def subscription_json(**fields) -> dict:
    sub = {
        "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "active",
        "metadata": {"organization_id": str(ORG)}, "cancel_at": None, "cancel_at_period_end": False, "discounts": [],
        "items": {"object": "list", "has_more": False, "url": "/v1/subscription_items", "data": [{
            "id": "si_1", "object": "subscription_item", "quantity": 7, "current_period_end": 1_800_000_000,
            "price": {"id": "price_biz_m", "object": "price", "lookup_key": "business_team_monthly",
                      "metadata": {"plan_key": "business_team", "interval": "month"}, "product": "prod_1",
                      "recurring": {"interval": "month", "interval_count": 1}},
        }]},
    }
    return sub | fields


def webhook_headers(payload: bytes, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> dict[str, str]:
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={digest}"}


def event_body(event_type: str, obj: dict, *, event_id: str = "evt_1", created: int = 1_790_000_000) -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": event_type, "created": created,
                       "api_version": API_VERSION, "data": {"object": obj}}).encode()


def test_subscription_webhook_refetches_with_expand_and_reads_item_period(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    body = event_body("customer.subscription.updated", {"id": "sub_1", "object": "subscription"})
    event = provider.parse_webhook(body=body, headers=webhook_headers(body))
    assert event.type == EVENT_SUBSCRIPTION_UPSERTED
    assert (event.id, event.organization_id, event.external_customer_id) == ("evt_1", ORG, "cus_1")
    assert (event.plan_key, event.interval, event.seats, event.status) == ("business_team", "month", 7, "active")
    assert event.current_period_end.timestamp() == 1_800_000_000
    assert event.occurred_at.timestamp() == 1_790_000_000
    expand = http.to("get", "/v1/subscriptions/sub_1")[0].query
    assert expand["expand[0]"] == "items.data.price.product"
    assert expand["expand[1]"] == "discounts.promotion_code"
    assert expand["expand[2]"] == "discounts.source.coupon"


@pytest.mark.parametrize("shape", ["source", "legacy"])
def test_discount_coupon_shapes(provider, http, shape):
    coupon = {"id": "WELCOME", "object": "coupon", "name": "Boas-vindas", "percent_off": 20.0, "duration": "once"}
    discount = {"id": "di_1", "object": "discount", "promotion_code": {"id": "promo_1", "code": "LANCA20"}}
    discount |= {"source": {"type": "coupon", "coupon": coupon}} if shape == "source" else {"coupon": coupon}
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json(discounts=[discount])
    body = event_body("customer.subscription.created", {"id": "sub_1", "object": "subscription"})
    event = provider.parse_webhook(body=body, headers=webhook_headers(body))
    assert event.coupon_code == "LANCA20"
    assert event.discount_summary["coupon_id"] == "WELCOME" and event.discount_summary["percent_off"] == 20.0


def test_invoice_paid_reads_parent_subscription_details(provider):
    obj = {"id": "in_1", "object": "invoice", "customer": "cus_1", "parent": {"type": "subscription_details",
           "subscription_details": {"subscription": "sub_1", "metadata": {"organization_id": str(ORG)}}}}
    body = event_body("invoice.paid", obj)
    event = provider.parse_webhook(body=body, headers=webhook_headers(body))
    assert (event.type, event.external_subscription_id, event.organization_id) == (EVENT_PAYMENT_SUCCEEDED, "sub_1", ORG)


def test_dispute_is_flagged_without_access_change(provider, http):
    http.routes["GET /v1/charges/ch_1"] = {"id": "ch_1", "object": "charge", "customer": "cus_9"}
    body = event_body("charge.dispute.created", {"id": "dp_1", "object": "dispute", "charge": "ch_1"})
    event = provider.parse_webhook(body=body, headers=webhook_headers(body))
    assert (event.type, event.external_customer_id) == (EVENT_RISK_FLAGGED, "cus_9")


# -- signature verification by the real SDK --------------------------------------------------------------------------


def test_webhook_signature_is_verified_before_any_stripe_call(provider, http):
    body = event_body("customer.subscription.updated", {"id": "sub_1", "object": "subscription"})
    good = webhook_headers(body)
    cases = {
        "tampered body": (body + b" ", good),
        "wrong secret": (body, webhook_headers(body, secret="whsec_other")),
        "replayed (stale timestamp)": (body, webhook_headers(body, timestamp=int(time.time()) - 3600)),
        "missing header": (body, {}),
        "garbage header": (body, {"Stripe-Signature": "nonsense"}),
    }
    for label, (payload, headers) in cases.items():
        with pytest.raises(WebhookRejected):
            provider.parse_webhook(body=payload, headers=headers)
        assert not http.requests, f"{label}: Stripe was called before the signature was accepted"


def test_signature_header_name_is_case_insensitive(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    body = event_body("customer.subscription.updated", {"id": "sub_1", "object": "subscription"})
    headers = {k.lower(): v for k, v in webhook_headers(body).items()}
    assert provider.parse_webhook(body=body, headers=headers).external_subscription_id == "sub_1"


def test_real_sdk_error_classes_are_recognised_by_name():
    from app.billing.stripe_provider import _is_card_error, _is_signature_error

    assert _is_signature_error(stripe.SignatureVerificationError("m", "h"))
    assert _is_card_error(stripe.CardError("declined", "param", "card_declined"))
    assert not _is_card_error(stripe.InvalidRequestError("x", "p"))


# -- change_plan / cancel --------------------------------------------------------------------------------------------


def local_subscription(**fields):
    values = {"external_subscription_id": "sub_1", "plan_key": "business_team", "interval": "month", "seats": 7}
    return SimpleNamespace(**(values | fields))


def test_change_plan_upgrade_sends_always_invoice_and_error_if_incomplete(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    http.routes["POST /v1/subscriptions/sub_1"] = subscription_json()
    provider.change_plan(subscription=local_subscription(), plan_key="business_team", interval="month", seats=9)
    sent = http.to("post", "/v1/subscriptions/sub_1")[0]
    assert sent.form["items[0][id]"] == "si_1" and sent.form["items[0][quantity]"] == "9"
    assert sent.form["items[0][price]"] == "price_biz_m"
    assert sent.form["proration_behavior"] == "always_invoice"
    assert sent.form["payment_behavior"] == "error_if_incomplete"
    assert sent.headers["Idempotency-Key"].startswith("arquivio-change-sub_1-")
    assert_params_match_sdk(decode_form(sent.form), SubscriptionUpdateParams)


def test_change_plan_downgrade_creates_prorations(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    http.routes["POST /v1/subscriptions/sub_1"] = subscription_json()
    provider.change_plan(subscription=local_subscription(), plan_key="business_team", interval="month", seats=3)
    assert http.to("post", "/v1/subscriptions/sub_1")[0].form["proration_behavior"] == "create_prorations"


def test_declined_upgrade_is_payment_failed_402(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    http.routes["POST /v1/subscriptions/sub_1"] = (402, {"error": {
        "type": "card_error", "code": "card_declined", "message": "Your card was declined.", "param": None}})
    with pytest.raises(EntitlementError) as error:
        provider.change_plan(subscription=local_subscription(), plan_key="business_team", interval="month", seats=9)
    assert (error.value.code, error.value.status_code) == ("payment_failed", 402)


def test_other_stripe_errors_propagate(provider, http):
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json()
    http.routes["POST /v1/subscriptions/sub_1"] = (400, {"error": {"type": "invalid_request_error", "message": "bad"}})
    with pytest.raises(stripe.InvalidRequestError):
        provider.change_plan(subscription=local_subscription(), plan_key="business_team", interval="month", seats=9)


def test_cancel_variants(provider, http):
    http.routes["POST /v1/subscriptions/sub_1"] = subscription_json()
    http.routes["DELETE /v1/subscriptions/sub_1"] = subscription_json(status="canceled")
    provider.cancel(subscription=local_subscription())
    assert http.to("post", "/v1/subscriptions/sub_1")[0].form == {"cancel_at_period_end": "true"}
    provider.cancel(subscription=local_subscription(), at_period_end=False)
    assert http.to("delete", "/v1/subscriptions/sub_1")


def test_list_invoices_reads_real_list_object(provider, http):
    http.routes["GET /v1/invoices"] = {"object": "list", "has_more": False, "url": "/v1/invoices", "data": [
        {"id": "in_1", "object": "invoice", "status": "paid", "number": "ARQ-0001", "total": 12900, "currency": "BRL",
         "created": 1_790_000_000, "hosted_invoice_url": "https://invoice.stripe.com/i/1", "invoice_pdf": "https://x/pdf"},
        {"id": "in_2", "object": "invoice", "status": "draft", "number": None, "total": 1, "currency": "brl",
         "created": 1_790_000_100}]}
    invoices = provider.list_invoices("cus_1")
    assert [i.id for i in invoices] == ["in_1"]
    assert (invoices[0].total, invoices[0].currency) == (12900, "brl")
    assert http.to("get", "/v1/invoices")[0].query == {"customer": "cus_1", "limit": "12"}


def test_get_field_never_returns_a_stripe_object_method():
    from stripe._util import convert_to_stripe_object

    sub = convert_to_stripe_object({"id": "sub_1", "object": "subscription"})
    assert get_field(sub, "update") is None
    assert get_field(sub, "id") == "sub_1"


# -- stripe-mock (OpenAPI-validated), optional -----------------------------------------------------------------------

MOCK_URL = os.environ.get("STRIPE_MOCK_URL", "http://localhost:12111")


def _mock_up() -> bool:
    parsed = urlparse(MOCK_URL)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
            return True
    except OSError:
        return False


needs_mock = pytest.mark.skipif(not _mock_up(), reason=f"stripe-mock is not listening at {MOCK_URL}")


@pytest.fixture()
def mock_provider():
    client = real_client(base_addresses={"api": MOCK_URL})
    return StripeBillingProvider(make_settings(stripe_pix_enabled=True), client=client), client


@needs_mock
def test_stripe_mock_accepts_checkout_portal_change_and_cancel(mock_provider):
    provider, _ = mock_provider
    for plan, seats in (("business_team", 5), ("personal_pro", 1)):
        for interval in ("month", "year"):
            for promo in (None, "promo_1"):
                session = provider.create_checkout(checkout(plan_key=plan, interval=interval, seats=seats,
                                                            external_customer_id="cus_1", promotion_code=promo))
                assert session.url.startswith("https://")
    assert provider.open_portal(PortalRequest(organization_id=ORG, external_customer_id="cus_1")).url
    provider.change_plan(subscription=local_subscription(), plan_key="business_team", interval="month", seats=6)
    provider.cancel(subscription=local_subscription())
    provider.cancel(subscription=local_subscription(), at_period_end=False)
    assert provider.list_invoices("cus_1") is not None


@needs_mock
def test_stripe_mock_accepts_catalog_sync_writes():
    from scripts.stripe_sync_catalog import apply_actions, plan_sync

    client = real_client(base_addresses={"api": MOCK_URL})
    actions = plan_sync(client)
    creates = [a for a in actions if a.op == "create"]
    assert creates, "the mock holds none of the Arquivio catalog, so creates are planned"
    assert len(apply_actions(client, creates)) == len(creates)


def test_invalid_promotion_code_id_is_a_422_not_a_500(provider, http):
    http.routes["POST /v1/checkout/sessions"] = (400, {"error": {
        "type": "invalid_request_error", "message": "No such promotion code: 'promo_nope'",
        "param": "discounts[0][promotion_code]"}})
    with pytest.raises(EntitlementError) as error:
        provider.create_checkout(checkout(promotion_code="promo_nope", external_customer_id="cus_1"))
    assert (error.value.code, error.value.status_code) == ("invalid_promotion_code", 422)


def test_other_invalid_requests_still_propagate(provider, http):
    http.routes["POST /v1/checkout/sessions"] = (400, {"error": {
        "type": "invalid_request_error", "message": "Invalid locale", "param": "locale"}})
    with pytest.raises(stripe.InvalidRequestError):
        provider.create_checkout(checkout(promotion_code="promo_x", external_customer_id="cus_1"))
    with pytest.raises(stripe.InvalidRequestError):  # no promotion code sent: never relabelled
        provider.create_checkout(checkout(external_customer_id="cus_1"))


def test_discount_with_unexpanded_coupon_id_keeps_the_code_and_id(provider, http):
    """Real sandbox shape (2026-09-30.endive): ``source.coupon`` is a bare ID unless ``discounts.source.coupon`` is expanded."""
    discount = {"id": "di_1", "object": "discount", "source": {"type": "coupon", "coupon": "E2E_LANCA20"},
                "promotion_code": {"id": "promo_1", "object": "promotion_code", "code": "E2ELANCA20",
                                   "promotion": {"type": "coupon", "coupon": "E2E_LANCA20"}}}
    http.routes["GET /v1/subscriptions/sub_1"] = subscription_json(discounts=[discount])
    body = event_body("customer.subscription.updated", {"id": "sub_1", "object": "subscription"})
    event = provider.parse_webhook(body=body, headers=webhook_headers(body))
    assert event.coupon_code == "E2ELANCA20"
    assert event.discount_summary == {"coupon_id": "E2E_LANCA20", "promotion_code": "E2ELANCA20"}
