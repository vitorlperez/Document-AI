# ruff: noqa: F811, RUF059
"""Personal vs business accounts: trial, seats, read-only, upgrade/downgrade, comps, billing without a provider."""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.audit_usage.models import AuditLog
from app.billing.provider import (
    EVENT_IGNORED,
    EVENT_PAYMENT_FAILED,
    EVENT_RISK_FLAGGED,
    EVENT_SUBSCRIPTION_CANCELED,
    EVENT_SUBSCRIPTION_UPSERTED,
    BillingEvent,
    CheckoutSession,
    PortalSession,
    WebhookRejected,
)
from app.identity.models import User
from app.organizations.models import BillingEvent as BillingEventRow
from app.organizations.models import (
    Membership,
    MembershipInvitation,
    MembershipRole,
    Organization,
    OrganizationComp,
    PlatformStaff,
    Subscription,
)
from tests.api.test_auth_and_invitations import auth_api, callback, make_membership  # noqa: F401

NOW = lambda: datetime.now(UTC)


def login(client, gateway, who: str = "owner") -> None:
    callback(client, gateway, code=who, email=f"{who}@example.test", subject=who)


def create_org(client, account_type: str = "personal", name: str = "Minha conta"):
    response = client.post("/organizations", json={"name": name, "account_type": account_type})
    assert response.status_code == 201, response.text
    return response.json()


def set_org(factory, organization_id, **fields) -> None:
    with factory.begin() as session:
        org = session.get(Organization, UUID(str(organization_id)))
        for key, value in fields.items():
            setattr(org, key, value)


def invite(client, org, email="pessoa@acme.co"):
    return client.post(f"/organizations/{org}/members/invitations", json={"email": email, "role": "member"})


# -- signup + trial -----------------------------------------------------------------------------------------------


def test_signup_defaults_to_a_personal_trial(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    created = create_org(client)
    assert (created["account_type"], created["plan_key"], created["entitlement_source"]) == ("personal", "personal_trial", "trial")
    assert created["read_only"] is False and created["entitlements"]["can_have_members"] is False
    ends = datetime.fromisoformat(created["trial_ends_at"])
    assert timedelta(days=13, hours=23) < ends - NOW() < timedelta(days=14, minutes=1)
    with factory() as session:
        org = session.get(Organization, UUID(created["id"]))
        assert org.created_by_user_id is not None and org.plan_key != "legacy"  # the endpoint never yields legacy


def test_business_signup_starts_a_business_trial(auth_api) -> None:
    client, _, gateway, _ = auth_api
    login(client, gateway)
    created = create_org(client, "business", "Acme")
    assert (created["account_type"], created["plan_key"]) == ("business", "business_trial")
    assert created["entitlements"]["can_have_members"] and created["entitlements"]["max_members"] == 5


def test_listing_and_me_expose_plan_state(auth_api) -> None:
    client, _, gateway, _ = auth_api
    login(client, gateway)
    created = create_org(client)
    listed = client.get("/organizations").json()[0]
    for key in ("account_type", "plan_key", "entitlement_source", "trial_ends_at", "read_only", "entitlements"):
        assert key in listed
    assert listed["id"] == created["id"]
    me = client.get("/me").json()
    assert me["organizations"][0]["plan_key"] == "personal_trial" and me["organizations"][0]["role"] == "owner"


@pytest.mark.trial_rules
def test_one_personal_org_and_one_trial_per_creator(auth_api) -> None:
    client, _, gateway, _ = auth_api
    login(client, gateway)
    create_org(client)
    second = client.post("/organizations", json={"name": "Outra", "account_type": "personal"})
    assert second.status_code == 403 and second.json()["code"] == "personal_org_limit"
    first_business = create_org(client, "business", "A")
    assert first_business["entitlement_source"] == "trial"
    again = create_org(client, "business", "B")  # allowed, but the trial was already consumed for this type
    assert (again["entitlement_source"], again["read_only"]) == ("expired", True)


def test_expired_trial_is_read_only_but_data_stays_readable(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    assert client.post(f"/organizations/{org}/automations", json={}).status_code != 402  # trial: not blocked by plan
    set_org(factory, org, trial_ends_at=NOW() - timedelta(minutes=1))
    listed = client.get("/organizations").json()[0]
    assert (listed["entitlement_source"], listed["read_only"]) == ("expired", True)
    assert client.get(f"/organizations/{org}/usage").status_code == 200  # reading keeps working
    blocked = invite(client, org)
    assert blocked.status_code == 402 and blocked.json()["code"] == "trial_expired"
    space = client.post(f"/organizations/{org}/spaces", json={"name": "Novo"})
    assert space.status_code == 402 and space.json()["code"] in {"trial_expired", "read_only"}
    from app.audit_usage.service import UsageLimitExceeded, UsageService
    from app.core.scoping import OrganizationScope

    with factory.begin() as session, pytest.raises(UsageLimitExceeded) as raised:
        UsageService(session).check_and_record(scope=OrganizationScope(UUID(org)), metric="questions", increment=1)
    assert raised.value.status_code == 402 and raised.value.code == "read_only"


# -- members and seats --------------------------------------------------------------------------------------------


def test_personal_account_cannot_invite(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client)["id"]
    refused = invite(client, org)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "personal accounts are single-user; upgrade to a business account to add people",
                              "code": "personal_no_members", "limit": 1, "used": None, "upgrade_to": "business_team"}
    with factory() as session:
        assert session.scalar(select(MembershipInvitation)) is None


def test_business_seats_count_members_plus_pending_and_accept_rechecks(auth_api) -> None:
    client, factory, gateway, delivery = auth_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    for index in range(4):  # owner + 4 = 5 seats of the business trial
        assert invite(client, org, f"p{index}@acme.co").status_code == 202
    full = invite(client, org, "p5@acme.co")
    assert full.status_code == 402
    assert (full.json()["code"], full.json()["limit"], full.json()["used"]) == ("seat_limit", 5, 5)
    assert full.json()["upgrade_to"] == "business_scale"
    # accept re-checks the seats: fill every seat with real members behind the pending invitations' back
    first_token = delivery.messages[0]["invitation_url"].rsplit("/", 1)[1]
    with factory.begin() as session:
        for index in range(4):
            user = User(email=f"filler{index}@example.test")
            session.add(user)
            session.flush()
            session.add(Membership(organization_id=UUID(org), user_id=user.id, role=MembershipRole.MEMBER, is_active=True))
    callback(client, gateway, code="p0", email="p0@acme.co", subject="p0")
    accepted = client.post(f"/invitations/{first_token}/accept")
    assert accepted.status_code == 402 and accepted.json()["code"] == "seat_limit"
    with factory.begin() as session:
        session.query(Membership).filter(Membership.user_id == session.scalar(
            select(User.id).where(User.email == "filler0@example.test"))).update({"is_active": False})
    assert client.post(f"/invitations/{first_token}/accept").status_code == 201


def test_legacy_organization_is_unchanged(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.test"))
        org = Organization(name="Velha")  # exactly what a pre-existing row looks like
        session.add(org)
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER, is_active=True))
        org_id = str(org.id)
    for index in range(12):  # far beyond any plan's seat cap
        assert invite(client, org_id, f"x{index}@acme.co").status_code == 202
    listed = client.get("/organizations").json()[0]
    assert (listed["plan_key"], listed["entitlement_source"], listed["read_only"]) == ("legacy", "legacy", False)
    assert listed["entitlements"]["max_members"] is None and listed["trial_ends_at"] is None
    assert client.get(f"/organizations/{org_id}/usage").json()["active_documents"]["limit"] == 3_000


# -- quotas -------------------------------------------------------------------------------------------------------


def test_personal_basic_quotas(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client)["id"]
    space = client.post(f"/organizations/{org}/spaces", json={"name": "Segundo"})  # trial allows 1 ("Geral" exists)
    assert space.status_code == 402 and space.json()["code"] == "space_limit"
    key = client.post(f"/organizations/{org}/api-keys", json={"name": "k", "scopes": ["search:read"]})
    assert key.status_code == 402 and key.json()["code"] == "feature_unavailable"
    set_org(factory, org, trial_ends_at=NOW() - timedelta(hours=1))
    with factory.begin() as session:  # a paid personal_pro subscription lifts the same limits
        session.add(Subscription(organization_id=UUID(org), provider="fake", external_subscription_id="s1",
                                 plan_key="personal_pro", status="active", seats=1))
    assert client.post(f"/organizations/{org}/api-keys", json={"name": "k", "scopes": ["search:read"]}).status_code == 201
    assert client.post(f"/organizations/{org}/spaces", json={"name": "Dois"}).status_code == 201


# -- upgrade / downgrade ------------------------------------------------------------------------------------------


def test_upgrade_in_place_keeps_the_organization_and_unlocks_members(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    created = create_org(client)
    org = created["id"]
    ends_before = created["trial_ends_at"]
    assert invite(client, org).status_code == 403
    upgraded = client.post(f"/organizations/{org}/upgrade", json={"name": "Acme Ltda", "plan_key": "business_team", "seats": 5})
    assert upgraded.status_code == 200, upgraded.text
    body = upgraded.json()
    assert (body["id"], body["name"], body["account_type"], body["plan_key"]) == (org, "Acme Ltda", "business", "business_trial")
    assert body["trial_ends_at"] == ends_before  # the trial days are preserved, not restarted
    assert invite(client, org).status_code == 202
    again = client.post(f"/organizations/{org}/upgrade", json={"name": "Acme Ltda", "plan_key": "business_team", "seats": 5})
    assert again.status_code == 200 and again.json()["id"] == org  # idempotent
    with factory() as session:
        assert session.scalar(select(AuditLog).where(AuditLog.action == "organization.upgraded")) is not None
        assert len(list(session.scalars(select(Organization)))) == 1


def test_upgrade_requires_an_owner_and_a_business_plan(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client)["id"]
    invalid = client.post(f"/organizations/{org}/upgrade", json={"name": "X", "plan_key": "personal_pro"})
    assert invalid.status_code == 422
    login(client, gateway, "stranger")
    assert client.post(f"/organizations/{org}/upgrade", json={"name": "X", "plan_key": "business_team"}).status_code == 403


def test_downgrade_rules(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    assert invite(client, org).status_code == 202
    blocked = client.post(f"/organizations/{org}/downgrade", json={})
    assert blocked.status_code == 409 and "pending_invitations" in blocked.json()["blockers"]
    with factory.begin() as session:
        session.query(MembershipInvitation).delete()
        user = User(email="colega@example.test")
        session.add(user)
        session.flush()
        session.add(Membership(organization_id=UUID(org), user_id=user.id, role=MembershipRole.MEMBER, is_active=True))
    members = client.post(f"/organizations/{org}/downgrade", json={})
    assert members.status_code == 409 and "members" in members.json()["blockers"]
    with factory.begin() as session:
        session.query(Membership).filter(Membership.role == MembershipRole.MEMBER).delete()
    set_org(factory, org, account_type_changed_at=NOW() - timedelta(days=1))
    cooling = client.post(f"/organizations/{org}/downgrade", json={})
    assert cooling.status_code == 409 and cooling.json()["blockers"] == ["cooldown"]
    set_org(factory, org, account_type_changed_at=NOW() - timedelta(days=45))
    done = client.post(f"/organizations/{org}/downgrade", json={"plan_key": "personal_basic"})
    assert done.status_code == 200 and done.json()["account_type"] == "personal"
    assert done.json()["id"] == org and done.json()["plan_key"] == "personal_trial"


# -- comps + platform admin ---------------------------------------------------------------------------------------


def make_staff(factory, email: str, role: str) -> None:
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == email))
        session.add(PlatformStaff(user_id=user.id, role=role))


def test_only_platform_admins_manage_comps_and_comp_beats_everything(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway, "customer")
    org = create_org(client, "business", "Cliente")["id"]
    set_org(factory, org, trial_ends_at=NOW() - timedelta(days=1))  # expired customer
    login(client, gateway, "support")
    make_staff(factory, "support@example.test", "support")
    body = {"plan_key": "business_team", "reason": "piloto", "expires_at": (NOW() + timedelta(days=30)).isoformat()}
    assert client.post(f"/platform/organizations/{org}/comps", json=body).status_code == 403
    login(client, gateway, "boss")
    make_staff(factory, "boss@example.test", "admin")
    seeded = client.post(f"/platform/organizations/{org}/comps", json=body | {"permanent": True, "expires_at": None})
    assert seeded.status_code == 201, seeded.text
    seeded_id = seeded.json()["id"]
    login(client, gateway, "support")  # support READS plan/comps (read-only) but never mutates
    viewed = client.get(f"/platform/organizations/{org}/entitlement")
    assert viewed.status_code == 200 and viewed.json()["entitlement_source"] == "comp" and len(viewed.json()["comps"]) == 1 and viewed.json()["staff_role"] == "support"
    assert [row["id"] for row in client.get("/platform/comps").json()] == [seeded_id]
    assert client.patch(f"/platform/organizations/{org}/comps/{seeded_id}", json={"expires_at": body["expires_at"]}).status_code == 403
    assert client.delete(f"/platform/organizations/{org}/comps/{seeded_id}").status_code == 403
    login(client, gateway, "customer")  # a non-staff user keeps being denied on the reads
    assert client.get(f"/platform/organizations/{org}/entitlement").status_code == 403
    assert client.get("/platform/comps").status_code == 403
    login(client, gateway, "boss")
    assert client.delete(f"/platform/organizations/{org}/comps/{seeded_id}").status_code == 204
    missing_reason = client.post(f"/platform/organizations/{org}/comps", json=body | {"reason": ""})
    assert missing_reason.status_code == 422
    no_expiry = client.post(f"/platform/organizations/{org}/comps", json={"plan_key": "business_team", "reason": "x"})
    assert no_expiry.status_code == 422
    wrong_type = client.post(f"/platform/organizations/{org}/comps", json=body | {"plan_key": "personal_pro"})
    assert wrong_type.status_code == 422
    granted = client.post(f"/platform/organizations/{org}/comps", json=body)
    assert granted.status_code == 201, granted.text
    comp_id = granted.json()["id"]
    view = client.get(f"/platform/organizations/{org}/entitlement").json()
    assert (view["entitlement_source"], view["plan_key"], view["read_only"]) == ("comp", "business_team", False)
    assert [row["revoked_at"] is None for row in view["comps"]].count(True) == 1  # the seeded comp stays in the history, revoked
    second = client.post(f"/platform/organizations/{org}/comps", json=body | {"plan_key": "business_scale"})
    assert second.status_code == 201  # replaces the previous one: a single active comp per organization
    with factory() as session:
        live = list(session.scalars(select(OrganizationComp).where(OrganizationComp.revoked_at.is_(None))))
        assert len(live) == 1 and live[0].plan_key == "business_scale"
    revoked = client.delete(f"/platform/organizations/{org}/comps/{second.json()['id']}")
    assert revoked.status_code == 204
    after = client.get(f"/platform/organizations/{org}/entitlement").json()
    assert after["entitlement_source"] == "expired"
    assert client.delete(f"/platform/organizations/{org}/comps/{comp_id}").status_code == 404
    with factory() as session:
        actions = {row.action for row in session.scalars(select(AuditLog).where(AuditLog.target_type == "organization_comp"))}
    assert {"comp.granted", "comp.revoked"} <= actions


def test_comp_extension_and_expiring_listing(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    login(client, gateway, "customer")
    org = create_org(client, "business", "Cliente")["id"]
    login(client, gateway, "boss")
    make_staff(factory, "boss@example.test", "admin")
    soon = (NOW() + timedelta(days=5)).isoformat()
    comp = client.post(f"/platform/organizations/{org}/comps", json={"plan_key": "business_team", "reason": "r", "expires_at": soon}).json()
    assert [row["id"] for row in client.get("/platform/comps?expiring_within=10").json()] == [comp["id"]]
    extended = client.patch(f"/platform/organizations/{org}/comps/{comp['id']}", json={"expires_at": (NOW() + timedelta(days=90)).isoformat()})
    assert extended.status_code == 200
    assert client.get("/platform/comps?expiring_within=10").json() == []


def test_cli_promotes_a_user_to_platform_admin(auth_api) -> None:
    import importlib.util
    import pathlib

    client, factory, gateway, _ = auth_api
    login(client, gateway, "boss")
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "platform_admin.py"
    spec = importlib.util.spec_from_file_location("platform_admin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with factory.begin() as session:
        staff = module.grant_staff(session, email="boss@example.test", role="admin")
        assert staff.role == "admin" and staff.is_active
    with factory.begin() as session:  # idempotent
        module.grant_staff(session, email="boss@example.test", role="admin")
        assert len(list(session.scalars(select(PlatformStaff)))) == 1
    assert client.get("/platform/comps").status_code == 200


# -- billing (provider-agnostic) ----------------------------------------------------------------------------------


def test_plans_catalog_is_public(auth_api) -> None:
    client, _, _, _ = auth_api
    body = client.get("/plans").json()
    assert body["currency"] == "BRL" and body["trial_days"] == 14 and body["billing_configured"] is False
    by_key = {plan["plan_key"]: plan for plan in body["plans"]}
    assert list(by_key) == ["personal_basic", "personal_pro", "business_team", "business_scale"]
    assert by_key["business_team"]["price_month_cents"] == 29900 and by_key["business_team"]["included_seats"] == 5
    assert by_key["business_scale"]["extra_seat_month_cents"] == 3900
    assert by_key["personal_basic"]["can_have_members"] is False


def test_billing_without_a_provider_answers_billing_not_configured(auth_api) -> None:
    client, _, gateway, _ = auth_api
    login(client, gateway)
    org = create_org(client)["id"]
    state = client.get(f"/organizations/{org}/billing").json()
    assert state["billing_configured"] is False and state["subscription"] is None
    for path, body in (("checkout", {"plan_key": "personal_basic"}), ("portal", {}), ("change-plan", {"plan_key": "personal_pro"}),
                       ("cancel", {})):
        response = client.post(f"/organizations/{org}/billing/{path}", json=body)
        assert response.status_code == 501, path
        assert response.json()["code"] == "billing_not_configured"
    webhook = client.post("/webhooks/billing/stripe", content=b"{}")
    assert webhook.status_code == 501 and webhook.json()["code"] == "billing_not_configured"


class FakeProvider:
    name = "fake"
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.next_event: BillingEvent | None = None

    def create_checkout(self, request):
        self.calls.append(("checkout", request.plan_key, request.seats, request.promotion_code))
        return CheckoutSession(url="https://pay.example.test/c/1", external_customer_id="cus_1")

    def open_portal(self, request):
        return PortalSession(url="https://pay.example.test/portal")

    def change_plan(self, *, subscription, plan_key, interval, seats):
        self.calls.append(("change_plan", plan_key, seats))

    def cancel(self, *, subscription, at_period_end=True):
        self.calls.append(("cancel", at_period_end))

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> BillingEvent:
        if headers.get("x-signature") != "ok":
            raise WebhookRejected("bad signature")
        return self.next_event

    def list_invoices(self, customer_id, limit=12):
        return []


@pytest.fixture()
def paid_api(auth_api):
    client, factory, gateway, delivery = auth_api
    provider = FakeProvider()
    client.app.state.billing_provider = provider
    return client, factory, gateway, provider


def event(org: str, kind: str = EVENT_SUBSCRIPTION_UPSERTED, event_id: str = "evt_1", at: datetime | None = None, **fields) -> BillingEvent:
    values = dict(id=event_id, type=kind, occurred_at=at or NOW(), organization_id=UUID(org), external_customer_id="cus_1",
                  external_subscription_id="sub_1", plan_key="business_team", interval="month", seats=7, status="active",
                  current_period_end=NOW() + timedelta(days=30))
    return BillingEvent(**(values | fields))


def post_webhook(client, provider, ev: BillingEvent, signature: str = "ok"):
    provider.next_event = ev
    return client.post("/webhooks/billing/fake", content=b"{}", headers={"x-signature": signature})


def test_checkout_and_portal_go_through_the_provider(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    org = create_org(client)["id"]
    assert client.get("/plans").json()["billing_configured"] is True
    wrong = client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "business_team", "seats": 5})
    assert wrong.status_code == 422 and wrong.json()["code"] == "invalid_plan"
    ok = client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro", "promotion_code": "LANCA20"})
    assert ok.status_code == 200 and ok.json() == {"url": "https://pay.example.test/c/1"}
    assert ("checkout", "personal_pro", 1, "LANCA20") in provider.calls  # the coupon rides through the interface
    assert client.post(f"/organizations/{org}/billing/portal").json() == {"url": "https://pay.example.test/portal"}
    with factory() as session:
        assert session.get(Organization, UUID(org)).billing_customer_id == "cus_1"


def test_webhook_applies_normalized_events_idempotently_and_in_order(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    assert post_webhook(client, provider, event(org), signature="bad").status_code == 400
    first = post_webhook(client, provider, event(org))
    assert first.status_code == 200 and first.json() == {"status": "processed"}
    state = client.get(f"/organizations/{org}/billing").json()
    assert (state["entitlement_source"], state["plan_key"], state["entitlements"]["max_members"]) == ("subscription", "business_team", 7)
    assert post_webhook(client, provider, event(org)).json() == {"status": "duplicate"}
    stale = post_webhook(client, provider, event(org, event_id="evt_old", at=NOW() - timedelta(hours=2), seats=2))
    assert stale.json() == {"status": "ignored"}
    assert client.get(f"/organizations/{org}/billing").json()["entitlements"]["max_members"] == 7
    failed = post_webhook(client, provider, event(org, EVENT_PAYMENT_FAILED, "evt_fail", status=None))
    assert failed.json() == {"status": "processed"}
    state = client.get(f"/organizations/{org}/billing").json()
    assert state["subscription"]["status"] == "past_due" and state["read_only"] is False and state["grace_ends_at"]
    canceled = post_webhook(client, provider, event(org, EVENT_SUBSCRIPTION_CANCELED, "evt_del", at=NOW() + timedelta(seconds=5)))
    assert canceled.json() == {"status": "processed"}
    state = client.get(f"/organizations/{org}/billing").json()
    assert state["entitlement_source"] in {"trial", "expired"}  # falls back to the next source


def test_first_subscription_clears_the_legacy_marker(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.test"))
        org = Organization(name="Velha")
        session.add(org)
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER, is_active=True))
        org_id = str(org.id)
    post_webhook(client, provider, event(org_id))
    post_webhook(client, provider, event(org_id, EVENT_SUBSCRIPTION_CANCELED, "evt_del", at=NOW() + timedelta(seconds=5)))
    state = client.get(f"/organizations/{org_id}/billing").json()
    assert (state["entitlement_source"], state["read_only"]) == ("expired", True)  # legacy ended with the first purchase


def test_upgrade_with_an_active_subscription_asks_the_provider(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    org = create_org(client)["id"]
    with factory.begin() as session:
        session.add(Subscription(organization_id=UUID(org), provider="fake", external_subscription_id="sub_9",
                                 plan_key="personal_pro", status="active", seats=1, interval="month"))
    response = client.post(f"/organizations/{org}/upgrade", json={"name": "Acme", "plan_key": "business_team", "seats": 6})
    assert response.status_code == 200
    assert ("change_plan", "business_team", 6) in provider.calls
    body = response.json()
    assert (body["account_type"], body["plan_key"], body["entitlement_source"]) == ("business", "business_team", "subscription")
    assert body["entitlements"]["max_members"] == 6


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_risk_and_ignored_events_are_recorded_without_touching_access(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    org = create_org(client, "business", "Acme")["id"]
    assert post_webhook(client, provider, event(org)).json() == {"status": "processed"}
    before = client.get(f"/organizations/{org}/billing").json()
    alerts = _Records()
    billing_logger = logging.getLogger("document_intelligence.billing")
    billing_logger.addHandler(alerts)
    try:
        flagged = post_webhook(client, provider, event(org, EVENT_RISK_FLAGGED, "evt_dispute", status="canceled", seats=1,
                                                     plan_key="personal_basic", at=NOW() + timedelta(seconds=5)))
    finally:
        billing_logger.removeHandler(alerts)
    assert flagged.status_code == 200 and flagged.json() == {"status": "processed"}
    assert [record.event for record in alerts.records] == [EVENT_RISK_FLAGGED]
    assert org in alerts.records[0].getMessage() and "evt_dispute" in alerts.records[0].getMessage()
    other = post_webhook(client, provider, event(org, EVENT_IGNORED, "evt_other", status="canceled", at=NOW() + timedelta(seconds=6)))
    assert other.status_code == 200 and other.json() == {"status": "ignored"}
    assert post_webhook(client, provider, event(org, EVENT_IGNORED, "evt_other")).json() == {"status": "duplicate"}
    after = client.get(f"/organizations/{org}/billing").json()
    for key in ("entitlement_source", "plan_key", "account_type", "read_only", "subscription", "entitlements"):
        assert after[key] == before[key], key  # no access change, no status/plan/seat regression
    with factory() as session:
        for event_id, kind in (("evt_dispute", EVENT_RISK_FLAGGED), ("evt_other", EVENT_IGNORED)):
            row = session.get(BillingEventRow, f"fake:{event_id}")
            assert row is not None and row.type == kind and row.processed_at is not None
        assert len(list(session.scalars(select(Subscription)))) == 1


def test_ignored_event_without_any_identifiers_is_accepted(paid_api) -> None:
    client, factory, _, provider = paid_api
    bare = BillingEvent(id="evt_ping", type=EVENT_IGNORED, occurred_at=NOW())
    assert post_webhook(client, provider, bare).json() == {"status": "ignored"}
    with factory() as session:
        assert session.get(BillingEventRow, "fake:evt_ping").processed_at is not None


def test_webhook_finds_the_organization_by_its_billing_customer(paid_api) -> None:
    client, factory, gateway, provider = paid_api
    login(client, gateway)
    org = create_org(client)["id"]
    other = create_org(client, "business", "Outra")["id"]
    assert client.post(f"/organizations/{org}/billing/checkout", json={"plan_key": "personal_pro"}).status_code == 200
    # No metadata on the event, or metadata pointing elsewhere: the stored customer decides.
    for event_id, organization_id in (("evt_c1", None), ("evt_c2", UUID(other))):
        response = post_webhook(client, provider, event(org, event_id=event_id, organization_id=organization_id,
                                                        external_subscription_id=f"sub_{event_id}", plan_key="personal_pro",
                                                        seats=1, at=NOW() + timedelta(seconds=len(event_id))))
        assert response.json() == {"status": "processed"}
    with factory() as session:
        owners = {row.organization_id for row in session.scalars(select(Subscription))}
    assert owners == {UUID(org)}
    assert client.get(f"/organizations/{org}/billing").json()["plan_key"] == "personal_pro"
    stranger = event(org, event_id="evt_c3", organization_id=None, external_customer_id="cus_unknown",
                     external_subscription_id="sub_unknown")
    assert post_webhook(client, provider, stranger).json() == {"status": "ignored"}


def test_build_provider_only_loads_the_stripe_adapter_when_asked(monkeypatch) -> None:
    import sys
    import types

    from app.billing.provider import NoBillingProvider, build_provider
    from app.core.config import Settings

    monkeypatch.setitem(sys.modules, "app.billing.stripe_provider", None)  # any import attempt would fail
    for name in ("none", "", "  ", "paypal"):
        assert isinstance(build_provider(name), NoBillingProvider)

    class StubStripe:
        name, configured = "stripe", True

        def __init__(self, settings) -> None:
            self.settings = settings

    monkeypatch.setitem(sys.modules, "app.billing.stripe_provider", types.SimpleNamespace(StripeBillingProvider=StubStripe))
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", billing_provider="stripe",
                        stripe_api_key="rk_test_x", stripe_webhook_secret="whsec_x", _env_file=None)
    built = build_provider(" Stripe ", settings)
    assert isinstance(built, StubStripe) and built.settings is settings


def test_create_app_hands_the_runtime_settings_to_the_provider(monkeypatch) -> None:
    import importlib
    import sys
    import types

    from app.core.config import Settings

    received = []

    class StubStripe:
        name, configured = "stripe", True

        def __init__(self, settings) -> None:
            received.append(settings)

    monkeypatch.setitem(sys.modules, "app.billing.stripe_provider", types.SimpleNamespace(StripeBillingProvider=StubStripe))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", billing_provider="stripe",
                        stripe_api_key="rk_test_x", stripe_webhook_secret="whsec_x", _env_file=None)
    app = importlib.import_module("app.main").create_app(settings)
    assert isinstance(app.state.billing_provider, StubStripe) and received == [settings]
