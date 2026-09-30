from uuid import uuid4

import pytest
from sqlalchemy import select

from app.access.models import McpConnection, OrganizationAccessSettings
from app.library.models import LibraryNode
from app.organizations.models import Membership, MembershipRole
from tests.access_helpers import seed_tenant
from tests.api.test_access_admin import admin_api  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401


def _path(org):
    return f"/organizations/{org}"


def test_enabling_requires_org_mcp_switch_and_replaces_previous_binding(admin_api):  # noqa: F811
    client, factory, org = admin_api
    assert client.put(_path(org) + "/mcp-connection", json={}).status_code == 403  # org switch is off
    assert client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True}).json() == {"mcp_enabled": True}
    first = client.put(_path(org) + "/mcp-connection", json={})
    assert first.status_code == 200 and first.json()["organization_id"] == str(org)
    assert client.get(_path(org) + "/mcp-connection").json()["active"] is True
    with factory() as session:
        assert session.query(McpConnection).filter(McpConnection.revoked_at.is_(None)).count() == 1


def test_second_organization_revokes_the_first_binding(admin_api):  # noqa: F811
    client, factory, org = admin_api
    client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True})
    client.put(_path(org) + "/mcp-connection", json={})
    with factory.begin() as session:
        user_id = session.scalar(select(Membership.user_id).where(Membership.organization_id == org))
        other = seed_tenant(factory, "Other", "x")
        session.add(Membership(organization_id=other.organization_id, user_id=user_id,
                               role=MembershipRole.MEMBER, is_active=True))
    assert client.put(_path(other.organization_id) + "/mcp-connection", json={}).status_code == 200
    with factory() as session:
        active = list(session.scalars(select(McpConnection).where(McpConnection.revoked_at.is_(None))))
        assert [c.organization_id for c in active] == [other.organization_id]
        assert session.query(McpConnection).count() == 2
    assert client.get(_path(org) + "/mcp-connection").json()["active"] is False


def test_delete_revokes_and_non_member_is_forbidden(admin_api):  # noqa: F811
    client, _factory, org = admin_api
    client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True})
    client.put(_path(org) + "/mcp-connection", json={})
    assert client.delete(_path(org) + "/mcp-connection").status_code == 204
    assert client.get(_path(org) + "/mcp-connection").json()["active"] is False
    for method in ("PUT", "GET", "DELETE"):
        assert client.request(method, _path(uuid4()) + "/mcp-connection", json={}).status_code == 403


def test_only_owner_or_admin_flips_the_org_switch(admin_api):  # noqa: F811
    client, factory, org = admin_api
    with factory.begin() as session:
        session.query(Membership).filter_by(organization_id=org).update({"role": MembershipRole.MEMBER})
    assert client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True}).status_code == 403
    with factory() as session:
        row = session.get(OrganizationAccessSettings, org)
        assert row is None or row.mcp_enabled is False


def test_node_ids_are_validated_against_the_organization(admin_api):  # noqa: F811
    client, factory, org = admin_api
    foreign = seed_tenant(factory, "Foreign", "secret")
    client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True})
    with factory() as session:
        node = session.scalar(select(LibraryNode.id).where(
            LibraryNode.organization_id == foreign.organization_id, LibraryNode.kind == "file"))
    assert client.put(_path(org) + "/mcp-connection", json={"node_ids": [str(node)]}).status_code == 422
    assert client.put(_path(org) + "/mcp-connection", json={"node_ids": [str(uuid4())]}).status_code == 422


@pytest.mark.parametrize("extra", [{"organization_id": "x"}, {"scopes": ["ask:run"]}])
def test_unknown_fields_are_rejected(admin_api, extra):  # noqa: F811
    client, _factory, org = admin_api
    client.put(_path(org) + "/mcp-settings", json={"mcp_enabled": True})
    assert client.put(_path(org) + "/mcp-connection", json=extra).status_code == 422
