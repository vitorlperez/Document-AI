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


def test_admin_can_configure_and_anonymous_requests_are_rejected(auth_api):  # noqa: F811
    client, factory, gateway, _ = auth_api
    path = f"/organizations/{create(client, gateway)}/onboarding"
    with factory.begin() as session:
        session.scalar(select(Membership)).role = MembershipRole.ADMIN
    assert client.get(path).json()["required"] is True
    assert client.patch(path, json={"step": "complete"}).json()["required"] is False
    client.cookies.clear()
    assert client.get(path).status_code == 401
    assert client.patch(path, json={"step": "complete"}).status_code == 401
    assert client.post(path + "/tour/complete").status_code == 401
