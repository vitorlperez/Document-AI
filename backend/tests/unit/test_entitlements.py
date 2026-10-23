"""Catalog + resolver: precedence comp > subscription > trial > legacy > expired, evaluated at read time."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit_usage.service import active_document_limit, monthly_limits
from app.core.config import Settings
from app.core.models import Base
from app.entitlements.catalog import SELLABLE_PLANS, plan_for, seat_price_cents
from app.entitlements.resolver import (
    entitlements_for,
    resolve_entitlement,
    validate_limits_override,
)
from app.identity.models import User
from app.organizations.models import Organization, OrganizationComp, Subscription

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        yield db
    engine.dispose()


def make_org(session: Session, **fields) -> Organization:
    org = Organization(name="Acme", **fields)
    session.add(org)
    session.flush()
    return org


def make_user(session: Session) -> User:
    user = User(email="admin@example.test")
    session.add(user)
    session.flush()
    return user


def sub(org: Organization, **fields) -> Subscription:
    values = dict(organization_id=org.id, provider="fake", external_subscription_id="sub_1", plan_key="business_team",
                  status="active", seats=8)
    return Subscription(**(values | fields))


def test_legacy_equals_settings_and_is_unrestricted(session) -> None:
    org = make_org(session)  # model defaults == what the migration gives existing rows
    ent = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (ent.source, ent.plan_key, ent.read_only, ent.account_type) == ("legacy", "legacy", False, "business")
    assert ent.can_have_members and ent.max_members is None and ent.max_spaces is None
    assert ent.monthly_limits() == monthly_limits(SETTINGS)
    assert ent.active_documents == active_document_limit(SETTINGS) == 3_000
    assert ent.max_automations == 20


def test_catalog_matches_the_owner_decisions() -> None:
    team, scale = plan_for("business_team", SETTINGS), plan_for("business_scale", SETTINGS)
    assert (team.price_month_cents, team.included_seats, team.extra_seat_month_cents, team.max_seats) == (29900, 5, 4900, 15)
    assert (scale.price_month_cents, scale.included_seats, scale.extra_seat_month_cents, scale.max_seats) == (89900, 20, 3900, 100)
    assert plan_for("personal_basic", SETTINGS).price_month_cents == 3900
    assert plan_for("personal_pro", SETTINGS).price_month_cents == 9900
    assert plan_for("business_team", SETTINGS).price_year_cents == 299000
    assert seat_price_cents(team, 8, "month") == 29900 + 3 * 4900
    assert not any(plan_for(key, SETTINGS).can_have_members for key in ("personal_basic", "personal_pro"))
    assert set(SELLABLE_PLANS) == {"personal_basic", "personal_pro", "business_team", "business_scale"}


def test_trial_is_local_and_expires_into_read_only(session) -> None:
    org = make_org(session, account_type="personal", plan_key="personal_trial", entitlement_source="trial",
                   trial_started_at=NOW - timedelta(days=1), trial_ends_at=NOW + timedelta(days=13))
    live = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (live.source, live.plan_key, live.read_only, live.can_have_members) == ("trial", "personal_trial", False, False)
    expired = resolve_entitlement(session, org, NOW + timedelta(days=14), SETTINGS)
    assert (expired.source, expired.plan_key, expired.read_only) == ("expired", "expired", True)


def test_precedence_comp_over_subscription_over_trial_over_legacy(session) -> None:
    admin = make_user(session)
    org = make_org(session, trial_started_at=NOW - timedelta(days=1), trial_ends_at=NOW + timedelta(days=5))
    assert resolve_entitlement(session, org, NOW, SETTINGS).source == "trial"  # trial beats legacy
    session.add(sub(org))
    session.flush()
    ent = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (ent.source, ent.plan_key, ent.max_members) == ("subscription", "business_team", 8)  # seats = quantity bought
    session.add(OrganizationComp(organization_id=org.id, plan_key="business_scale", reason="pilot",
                                 granted_by_user_id=admin.id, expires_at=NOW + timedelta(days=30)))
    session.flush()
    comp = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (comp.source, comp.plan_key, comp.max_members) == ("comp", "business_scale", 20)
    after_comp = resolve_entitlement(session, org, NOW + timedelta(days=31), SETTINGS)
    assert after_comp.source == "subscription"  # a comp expires by time alone, no job involved


def test_seats_are_clamped_to_the_plan_range(session) -> None:
    org = make_org(session)
    session.add(sub(org, seats=99))
    session.flush()
    assert resolve_entitlement(session, org, NOW, SETTINGS).max_members == 15
    other = make_org(session)
    session.add(sub(other, external_subscription_id="sub_2", seats=1))
    session.flush()
    assert resolve_entitlement(session, other, NOW, SETTINGS).max_members == 5  # never below the included seats


@pytest.mark.parametrize(("fields", "expected_source", "read_only"), [
    ({"status": "past_due", "past_due_since": NOW - timedelta(days=3)}, "subscription", False),
    ({"status": "past_due", "past_due_since": NOW - timedelta(days=8)}, "subscription", True),
    ({"status": "unpaid"}, "subscription", True),
    ({"status": "paused"}, "subscription", True),
    ({"status": "canceled"}, "expired", True),
    ({"status": "incomplete"}, "expired", True),
    ({"status": "active", "cancel_at_period_end": True, "current_period_end": NOW - timedelta(days=1)}, "expired", True),
    ({"status": "active", "cancel_at_period_end": True, "current_period_end": NOW + timedelta(days=1)}, "subscription", False),
])
def test_subscription_status_to_access(session, fields, expected_source, read_only) -> None:
    org = make_org(session, entitlement_source="subscription")  # legacy marker already cleared by a purchase
    session.add(sub(org, **fields))
    session.flush()
    ent = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (ent.source, ent.read_only) == (expected_source, read_only)


def test_legacy_marker_survives_a_comp_and_comes_back(session) -> None:
    admin = make_user(session)
    org = make_org(session)
    session.add(OrganizationComp(organization_id=org.id, plan_key="business_team", reason="x",
                                 granted_by_user_id=admin.id, expires_at=NOW + timedelta(days=1)))
    session.flush()
    assert resolve_entitlement(session, org, NOW, SETTINGS).source == "comp"
    assert resolve_entitlement(session, org, NOW + timedelta(days=2), SETTINGS).source == "legacy"


def test_comp_of_the_wrong_account_type_is_ignored(session) -> None:
    admin = make_user(session)
    org = make_org(session, account_type="personal", plan_key="personal_trial", entitlement_source="trial",
                   trial_ends_at=NOW + timedelta(days=3))
    session.add(OrganizationComp(organization_id=org.id, plan_key="business_team", reason="x", granted_by_user_id=admin.id))
    session.flush()
    assert resolve_entitlement(session, org, NOW, SETTINGS).source == "trial"


def test_limits_override_is_validated_and_unlimited_is_explicit() -> None:
    assert validate_limits_override({"max_members": "unlimited", "max_automations": 50, "mcp_enabled": True}) == {
        "max_members": None, "max_automations": 50, "mcp_enabled": True}
    for bad in ({"price": 1}, {"max_members": -1}, {"max_members": "lots"}, {"mcp_enabled": "yes"}):
        with pytest.raises(ValueError):
            validate_limits_override(bad)


def test_override_applies_only_to_a_comp(session) -> None:
    admin = make_user(session)
    org = make_org(session)
    session.add(OrganizationComp(organization_id=org.id, plan_key="business_team", reason="negotiated",
                                 granted_by_user_id=admin.id, limits_override={"max_members": 40, "monthly_questions": None}))
    session.flush()
    ent = resolve_entitlement(session, org, NOW, SETTINGS)
    assert (ent.max_members, ent.monthly_questions, ent.active_documents) == (40, None, 3_000)


def test_entitlements_are_cached_per_session_and_invalidated(session) -> None:
    org = make_org(session)
    first = entitlements_for(session, org.id, SETTINGS)
    assert entitlements_for(session, org.id, SETTINGS) is first
    from app.entitlements.resolver import invalidate

    invalidate(session, org.id)
    assert entitlements_for(session, org.id, SETTINGS) is not first


def test_unknown_organization_behaves_as_before_the_feature(session) -> None:
    from uuid import uuid4

    ent = entitlements_for(session, uuid4(), SETTINGS)
    assert ent.source == "legacy" and not ent.read_only
