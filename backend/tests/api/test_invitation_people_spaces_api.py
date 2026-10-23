"""F-GAP-1/3: invitation with Spaces and the minimal people list for Space managers."""
# ruff: noqa: F811

from uuid import UUID

import pytest
from sqlalchemy import select

from app.identity.models import User
from app.organizations.models import MembershipInvitation, MembershipRole
from app.spaces.models import Space, SpaceMember
from tests.api.test_auth_and_invitations import (  # noqa: F401
    auth_api,
    callback,
    invitation_token,
    make_membership,
)

pytestmark = pytest.mark.no_auto_spaces


def setup_org(auth_api):
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    org = client.post("/organizations", json={"account_type": "business", "name": "Acme"}).json()["id"]
    return client, factory, gateway, delivery, org


def make_space(client, org, name):
    response = client.post(f"/organizations/{org}/spaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def invite(client, org, **extra):
    return client.post(
        f"/organizations/{org}/members/invitations",
        json={"email": "invitee@acme.co", "role": "member", **extra},
    )


def accept(client, gateway, delivery):
    callback(client, gateway, code="invitee", email="invitee@acme.co", subject="invitee")
    response = client.post(f"/invitations/{invitation_token(delivery)}/accept")
    assert response.status_code == 201
    return response


def spaces_of(factory, email):
    with factory() as session:
        user_id = session.scalar(select(User.id).where(User.email == email))
        return {
            name for (name,) in session.execute(
                select(Space.name).join(SpaceMember, SpaceMember.space_id == Space.id).where(
                    SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        }


def test_invitation_with_space_ids_joins_only_those_spaces(auth_api):
    client, factory, gateway, delivery, org = setup_org(auth_api)
    rh = make_space(client, org, "RH")
    assert invite(client, org, space_ids=[rh]).status_code == 202
    with factory() as session:
        stored = session.scalar(select(MembershipInvitation))
        assert stored.space_ids == [rh]
    accept(client, gateway, delivery)
    assert spaces_of(factory, "invitee@acme.co") == {"RH"}


def test_invitation_without_space_ids_joins_default_space(auth_api):
    client, factory, gateway, delivery, org = setup_org(auth_api)
    assert invite(client, org).status_code == 202
    accept(client, gateway, delivery)
    assert spaces_of(factory, "invitee@acme.co") == {"Geral"}


def test_invitation_with_empty_space_ids_falls_back_to_default_space(auth_api):
    client, factory, gateway, delivery, org = setup_org(auth_api)
    assert invite(client, org, space_ids=[]).status_code == 202
    accept(client, gateway, delivery)
    assert spaces_of(factory, "invitee@acme.co") == {"Geral"}


def test_invitation_refuses_foreign_or_archived_space_without_side_effects(auth_api):
    client, factory, _gateway, delivery, org = setup_org(auth_api)
    other_org = client.post("/organizations", json={"account_type": "business", "name": "Other"}).json()["id"]
    foreign = make_space(client, other_org, "Foreign")
    archived = make_space(client, org, "Velho")
    assert client.delete(f"/organizations/{org}/spaces/{archived}").status_code == 204
    for bad in (foreign, archived, "00000000-0000-0000-0000-000000000000"):
        response = invite(client, org, space_ids=[bad])
        assert response.status_code == 422, bad
        assert response.json() == {"detail": "space not found"}
    assert invite(client, org, space_ids=[make_space(client, org, "RH"), foreign]).status_code == 422
    with factory() as session:
        assert session.scalars(select(MembershipInvitation)).first() is None
    assert delivery.messages == []


def test_space_archived_after_invitation_falls_back_to_default_on_accept(auth_api):
    client, factory, gateway, delivery, org = setup_org(auth_api)
    rh = make_space(client, org, "RH")
    assert invite(client, org, space_ids=[rh]).status_code == 202
    assert client.delete(f"/organizations/{org}/spaces/{rh}").status_code == 204
    accept(client, gateway, delivery)
    assert spaces_of(factory, "invitee@acme.co") == {"Geral"}


def seed_people(auth_api):
    """owner, admin, plain member, a manager of RH (org member), and a person in another org."""
    client, factory, gateway, _delivery, org = setup_org(auth_api)
    rh = make_space(client, org, "RH")
    ids = {}
    for who, role in (("admin", MembershipRole.ADMIN), ("plain", MembershipRole.MEMBER), ("boss", MembershipRole.MEMBER)):
        callback(client, gateway, code=who, email=f"{who}@example.test", subject=who)
        with factory() as session:
            ids[who] = session.scalar(select(User.id).where(User.email == f"{who}@example.test"))
        make_membership(factory, organization_id=UUID(org), user_id=ids[who], role=role)
    callback(client, gateway, code="stranger", email="stranger@elsewhere.test", subject="stranger")
    client.post("/organizations", json={"account_type": "business", "name": "Elsewhere"})
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    assert client.post(f"/organizations/{org}/spaces/{rh}/members", json={"user_id": str(ids["boss"]), "role": "manager"}).status_code == 201
    return client, gateway, org, rh, ids


def as_user(client, gateway, who):
    callback(client, gateway, code=f"again-{who}", email=f"{who}@example.test", subject=who)


def test_people_list_is_minimal_and_open_to_owner_admin_and_space_manager(auth_api):
    client, gateway, org, _rh, ids = seed_people(auth_api)
    for who in ("owner", "admin", "boss"):
        as_user(client, gateway, who)
        response = client.get(f"/organizations/{org}/people")
        assert response.status_code == 200, who
        rows = response.json()
        assert {tuple(sorted(row)) for row in rows} == {("email", "user_id")}
        assert [row["email"] for row in rows] == sorted(
            ["owner@example.test", "admin@example.test", "plain@example.test", "boss@example.test"])
        assert str(ids["boss"]) in {row["user_id"] for row in rows}
        assert "stranger@elsewhere.test" not in str(rows)


def test_people_list_refuses_plain_members_and_outsiders(auth_api):
    client, gateway, org, _rh, _ids = seed_people(auth_api)
    as_user(client, gateway, "plain")
    assert client.get(f"/organizations/{org}/people").status_code == 403
    callback(client, gateway, code="stranger-again", email="stranger@elsewhere.test", subject="stranger")
    assert client.get(f"/organizations/{org}/people").status_code == 403


def test_manager_of_archived_space_loses_people_list(auth_api):
    client, gateway, org, rh, _ids = seed_people(auth_api)
    callback(client, gateway, code="owner-again", email="owner@example.test", subject="owner")
    assert client.delete(f"/organizations/{org}/spaces/{rh}").status_code == 204
    as_user(client, gateway, "boss")
    assert client.get(f"/organizations/{org}/people").status_code == 403


def test_owner_members_list_now_carries_user_id(auth_api):
    client, gateway, org, _rh, _ids = seed_people(auth_api)
    callback(client, gateway, code="owner-three", email="owner@example.test", subject="owner")
    rows = client.get(f"/organizations/{org}/members").json()
    assert all(row["user_id"] for row in rows) and {"id", "email", "role", "user_id"} == set(rows[0])
    as_user(client, gateway, "boss")
    assert client.get(f"/organizations/{org}/members").status_code == 403
