from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.identity.models import User
from app.organizations.models import Membership, MembershipRole
from tests.api.test_auth_and_invitations import auth_api, callback, make_membership  # noqa: F401


def create(client, gateway):
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    return client.post("/organizations", json={"name": "Nova equipe"}).json()["id"]


def test_first_organization_resumes_and_completion_survives_another_login(auth_api):  # noqa: F811
    client, _, gateway, _ = auth_api
    org = create(client, gateway)
    path = f"/organizations/{org}/onboarding"
    initial = client.get(path)
    assert initial.status_code == 200
    assert initial.json() == {"step": "welcome", "required": True, "tour_required": False}
    assert client.patch(path, json={"step": "integrations"}).json()["step"] == "integrations"
    callback(client, gateway, code="resume", email="owner@example.test", subject="owner")
    assert client.get(path).json()["step"] == "integrations"
    assert client.patch(path, json={"step": "complete"}).json() == {
        "step": "complete", "required": False, "tour_required": True,
    }
    assert client.post(path + "/tour/complete").json()["tour_required"] is False
    callback(client, gateway, code="again", email="owner@example.test", subject="owner")
    assert client.get(path).json() == {
        "step": "complete", "required": False, "tour_required": False,
    }
    # A stale tab cannot restart a completed organization.
    assert client.patch(path, json={"step": "welcome"}).json()["required"] is False


def test_skip_from_welcome_and_tour_completion_are_idempotent(auth_api):  # noqa: F811
    client, _, gateway, _ = auth_api
    path = f"/organizations/{create(client, gateway)}/onboarding"
    assert client.post(path + "/tour/complete").status_code == 409
    for _ in range(2):
        assert client.patch(path, json={"step": "complete"}).json()["tour_required"] is True
    for _ in range(2):
        assert client.post(path + "/tour/complete").json()["tour_required"] is False
    assert client.patch(path, json={"step": "invalid"}).status_code == 422


@pytest.mark.parametrize("role", [MembershipRole.ADMIN, MembershipRole.MEMBER])
def test_onboarding_is_org_scoped_and_tour_is_membership_scoped(auth_api, role):  # noqa: F811
    client, factory, gateway, _ = auth_api
    org = create(client, gateway)
    path = f"/organizations/{org}/onboarding"
    client.patch(path, json={"step": "complete"})
    client.post(path + "/tour/complete")
    callback(client, gateway, code="other", email="other@example.test", subject="other")
    assert client.get(path).status_code == 403
    assert client.patch(path, json={"step": "complete"}).status_code == 403
    assert client.post(path + "/tour/complete").status_code == 403
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "other@example.test"))
        user_id = user.id
    membership = make_membership(factory, organization_id=UUID(org), user_id=user_id, role=role)
    assert client.get(path).json()["tour_required"] is True
    assert client.post(path + "/tour/complete").json()["tour_required"] is False
    assert client.get(f"/organizations/{uuid4()}/onboarding").status_code == 403
    with factory.begin() as session:
        session.get(Membership, membership.id).is_active = False
    assert client.get(path).status_code == 403


def test_member_does_not_configure_org_and_new_org_has_independent_state(auth_api):  # noqa: F811
    client, factory, gateway, _ = auth_api
    org = create(client, gateway)
    path = f"/organizations/{org}/onboarding"
    with factory.begin() as session:
        session.scalar(select(Membership)).role = MembershipRole.MEMBER
    assert client.get(path).json()["required"] is False

    assert client.patch(path, json={"step": "complete"}).status_code == 403
    with factory.begin() as session:
        session.scalar(select(Membership)).role = MembershipRole.OWNER
    client.patch(path, json={"step": "complete"})
    other = client.post("/organizations", json={"name": "Outra equipe"}).json()["id"]
    assert client.get(f"/organizations/{other}/onboarding").json()["required"] is True
    assert client.get(path).json()["required"] is False


def test_admin_cannot_configure_and_anonymous_requests_are_rejected(auth_api):  # noqa: F811
    client, factory, gateway, _ = auth_api
    path = f"/organizations/{create(client, gateway)}/onboarding"
    with factory.begin() as session:
        session.scalar(select(Membership)).role = MembershipRole.ADMIN
    assert client.get(path).json() == {"step": "welcome", "required": False, "tour_required": True}
    assert client.patch(path, json={"step": "complete"}).status_code == 403
    assert client.post(path + "/tour/complete").status_code == 200
    client.cookies.clear()
    assert client.get(path).status_code == 401
    assert client.patch(path, json={"step": "complete"}).status_code == 401
    assert client.post(path + "/tour/complete").status_code == 401


@pytest.mark.parametrize("step", ["integrations", "complete"])
@pytest.mark.parametrize("role", [MembershipRole.ADMIN, MembershipRole.MEMBER])
def test_demoted_owner_cannot_advance_with_cached_membership(auth_api, step, role):  # noqa: F811
    from sqlalchemy import update

    from app.organizations.onboarding import OnboardingNotAllowed, OnboardingService

    client, factory, gateway, _ = auth_api
    org = UUID(create(client, gateway))
    with factory.begin() as session:
        session.scalar(select(Membership)).role = MembershipRole.OWNER
    with factory() as session:
        membership = session.scalar(select(Membership))
        service = OnboardingService(session)
        assert service.state(organization_id=org, user_id=membership.user_id)["required"]
        # A second transaction changes the role while this session retains its identity map.
        with factory.begin() as other:
            other.execute(update(Membership).where(Membership.id == membership.id).values(role=role))
        with pytest.raises(OnboardingNotAllowed):
            service.advance(organization_id=org, user_id=membership.user_id, step=step)
        session.rollback()
    assert client.get(f"/organizations/{org}/onboarding").json()["step"] == "welcome"
    assert client.patch(f"/organizations/{org}/onboarding", json={"step": step}).status_code == 403


@pytest.mark.parametrize("role", [MembershipRole.ADMIN, MembershipRole.MEMBER])
@pytest.mark.parametrize("setup_complete", [False, True])
def test_new_invite_only_gets_tour_even_when_owner_setup_is_pending(auth_api, role, setup_complete):  # noqa: F811
    client, _, gateway, delivery = auth_api
    org = create(client, gateway)
    path = f"/organizations/{org}/onboarding"
    if setup_complete:
        client.patch(path, json={"step": "complete"})
    email = f"invited-{role.value}@example.com"
    assert client.post(f"/organizations/{org}/members/invitations", json={
        "email": email, "role": role.value,
    }).status_code == 202
    token = delivery.messages[-1]["invitation_url"].rsplit("/", 1)[1]
    callback(client, gateway, code="invite", email=email, subject=email)
    assert client.post(f"/invitations/{token}/accept").status_code == 201
    assert client.get(path).json() == {
        "step": "complete" if setup_complete else "welcome",
        "required": False, "tour_required": True,
    }
    for step in ["welcome", "integrations", "complete"]:
        assert client.patch(path, json={"step": step}).status_code == 403
    assert client.post(path + "/tour/complete").json()["tour_required"] is False
    callback(client, gateway, code="return", email=email, subject=email)
    assert client.get(path).json()["tour_required"] is False
    callback(client, gateway, code="owner-return", email="owner@example.test", subject="owner")
    assert client.get(path).json()["required"] is (not setup_complete)
