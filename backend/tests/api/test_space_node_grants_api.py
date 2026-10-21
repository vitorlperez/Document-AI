"""Folder-level grants end to end: admin tree + PUT, then what each person reaches over HTTP (library, questions,
documents, API key, MCP-style fetch). Sibling not granted and person outside the Space are a uniform 404."""

import pytest
from sqlalchemy import select

from app.access.models import OrganizationAccessSettings
from app.access.ratelimit import InMemoryRateLimiter
from app.organizations.models import Membership, MembershipRole
from app.spaces.models import SpaceNodeGrant
from tests.access_helpers import Tenant, bearer, mint_key
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    FakeSemanticProvider,
    login,
    search_api,
)
from tests.space_node_helpers import Tree
from tests.spaces_helpers import bind_login_identities, seed_world

DISCLOSURE = {"text_version": "v1"}


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter()
    client.app.state.semantic_provider = FakeSemanticProvider()
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        tree = Tree(session, world)
        session.add(OrganizationAccessSettings(organization_id=world.organization_id, public_api_enabled=True,
                                               mcp_enabled=True))
        nodes = {"contratos": tree.contratos, "financeiro": tree.financeiro, "y2026": tree.y2026,
                 **{f"file_{key}": value for key, value in tree.node.items()}}
        documents = dict(tree.doc)
        shared = tree.shared
    return client, factory, gateway, world, nodes, documents, shared


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def put(client, world, body, space="rh"):
    return client.put(f"/organizations/{world.organization_id}/spaces/{world.spaces[space]}/folders", json=body)


def children(client, world, node):
    return client.get(f"/library/nodes/{node}/children?organization_id={world.organization_id}")


def grant(client, gateway, world, nodes, **kw):
    as_user(client, gateway, "eva")
    response = put(client, world, {"grant_nodes": [str(nodes["y2026"])], "disclosure": DISCLOSURE, **kw})
    assert response.status_code == 200, response.text
    return response


def ask(client, world, question="qual o contrato?"):
    return client.post(f"/organizations/{world.organization_id}/questions",
                       json={"question": question, "scope": "organization"})


def test_admin_grants_a_subfolder_and_reads_it_back(world_api):
    client, factory, gateway, world, nodes, _documents, _shared = world_api
    body = grant(client, gateway, world, nodes).json()
    assert body["granted_nodes"] == [str(nodes["y2026"])] and body["revoked_nodes"] == []
    again = put(client, world, {"grant_nodes": [str(nodes["y2026"])], "disclosure": DISCLOSURE}).json()
    assert again["granted_nodes"] == []  # idempotent
    with factory() as session:
        assert len(list(session.scalars(select(SpaceNodeGrant).where(SpaceNodeGrant.revoked_at.is_(None))))) == 1
    as_user(client, gateway, "bruno")  # a member of RH reads the list
    listed = client.get(f"/organizations/{world.organization_id}/spaces/{world.spaces['rh']}/node-grants").json()
    assert [(item["name"], item["path"]) for item in listed] == [("2026", "Google Drive/Contratos/2026")]
    assert listed[0]["ancestor_ids"] == [str(nodes["contratos"]), str(world.nodes["source"])]
    as_user(client, gateway, "daniel")  # not in RH: the Space does not exist for them
    assert client.get(
        f"/organizations/{world.organization_id}/spaces/{world.spaces['rh']}/node-grants").status_code == 404


def test_only_org_admins_change_folders_and_foreign_nodes_are_refused(world_api):
    client, _factory, gateway, world, nodes, _documents, _shared = world_api
    body = {"grant_nodes": [str(nodes["y2026"])], "disclosure": DISCLOSURE}
    as_user(client, gateway, "ana")  # manager of RH, not an org admin
    assert put(client, world, body).status_code == 403
    as_user(client, gateway, "eva")
    assert put(client, world, {"grant_nodes": [str(world.nodes["source"])], "disclosure": DISCLOSURE}).status_code == 403
    assert put(client, world, {"grant_nodes": [str(nodes["file_solto"])], "disclosure": DISCLOSURE}).status_code == 403
    assert put(client, world, {"grant_nodes": [str(nodes["y2026"])]}).status_code == 422  # disclosure is required


def test_library_shows_only_the_granted_subtree_and_a_sibling_is_a_uniform_404(world_api):
    client, _factory, gateway, world, nodes, _documents, _shared = world_api
    grant(client, gateway, world, nodes)
    as_user(client, gateway, "bruno")
    assert [item["name"] for item in children(client, world, nodes["contratos"]).json()["items"]] == ["2026"]
    assert [item["name"] for item in children(client, world, nodes["y2026"]).json()["items"]] == ["c2026.pdf"]
    sibling = children(client, world, nodes["financeiro"])
    assert sibling.status_code == 404
    assert client.get(f"/library/search?organization_id={world.organization_id}&query=balanco").json()["items"] == []
    as_user(client, gateway, "daniel")  # outside the Space: same answer as a node that does not exist
    assert children(client, world, nodes["y2026"]).status_code == 404
    assert children(client, world, nodes["contratos"]).status_code == 404


def test_questions_and_documents_stay_inside_the_grant(world_api):
    client, _factory, gateway, world, nodes, documents, _shared = world_api
    grant(client, gateway, world, nodes)
    as_user(client, gateway, "bruno")
    cited = {item["document_id"] for item in ask(client, world, "contrato").json()["citations"]}
    assert str(documents["solto"]) not in cited and str(documents["balanco"]) not in cited
    org = world.organization_id
    assert client.get(f"/organizations/{org}/documents/{documents['c2026']}/view").status_code == 200
    assert client.get(f"/organizations/{org}/documents/{documents['solto']}/view").status_code == 404
    assert client.get(f"/organizations/{org}/documents/{documents['balanco']}/view").status_code == 404
    as_user(client, gateway, "daniel")
    assert client.get(f"/organizations/{org}/documents/{documents['c2026']}/view").status_code == 404
    found = client.post(f"/organizations/{org}/search", json={"query": "contrato"}).json()["results"]
    assert str(documents["c2026"]) not in {item["document_id"] for item in found}
    as_user(client, gateway, "bruno")
    found = client.post(f"/organizations/{org}/search", json={"query": "contrato"}).json()["results"]
    assert {item["document_id"] for item in found} == {str(documents["c2026"])}


def test_api_key_and_fetch_reach_only_the_grant(world_api):
    client, factory, gateway, world, nodes, documents, shared = world_api
    grant(client, gateway, world, nodes)
    client.cookies.clear()  # the key alone authenticates
    with factory.begin() as session:  # API keys belong to org admins; being admin grants no Space reading
        for who in ("bruno", "daniel"):
            session.query(Membership).filter_by(user_id=world.users[who]).update({"role": MembershipRole.ADMIN})
    tenant = Tenant(world.organization_id, world.users["bruno"], shared, documents["c2026"])
    key = mint_key(factory, tenant)
    results = client.post("/v1/search", json={"query": "contrato"}, headers=bearer(key)).json()["results"]
    assert [item["id"] for item in results] == [str(documents["c2026"])]
    assert client.get(f"/v1/documents/{documents['c2026']}", headers=bearer(key)).status_code == 200
    assert client.get(f"/v1/documents/{documents['solto']}", headers=bearer(key)).status_code == 404
    assert client.get(f"/v1/documents/{documents['balanco']}", headers=bearer(key)).status_code == 404
    outsider = mint_key(factory, Tenant(world.organization_id, world.users["daniel"], shared, documents["c2026"]))
    assert client.post("/v1/search", json={"query": "contrato"}, headers=bearer(outsider)).json()["results"] == []


def test_revoking_cuts_access_on_the_next_request(world_api):
    client, _factory, gateway, world, nodes, _documents, _shared = world_api
    grant(client, gateway, world, nodes)
    as_user(client, gateway, "bruno")
    assert children(client, world, nodes["y2026"]).status_code == 200
    as_user(client, gateway, "eva")
    revoked = put(client, world, {"revoke_nodes": [str(nodes["y2026"])]}).json()
    assert revoked["revoked_nodes"] == [str(nodes["y2026"])]
    as_user(client, gateway, "bruno")
    assert children(client, world, nodes["y2026"]).status_code == 404


def test_admin_folder_tree_lists_names_only_and_members_cannot(world_api):
    client, _factory, gateway, world, nodes, _documents, _shared = world_api
    base = f"/organizations/{world.organization_id}/spaces/folder-tree"
    as_user(client, gateway, "eva")
    listed = client.get(f"{base}/nodes/{nodes['contratos']}/children").json()["items"]
    assert [(item["name"], item["has_children"]) for item in listed] == [("2026", False)]
    assert [item["name"] for item in client.get(f"{base}/nodes/{world.nodes['source']}/children").json()["items"]] == [
        "Contratos", "Financeiro"]
    assert client.get(f"{base}/nodes/{nodes['file_solto']}/children").status_code == 404  # a file has no subfolders
    assert client.get(f"{base}/roots").status_code == 200
    as_user(client, gateway, "bruno")
    assert client.get(f"{base}/roots").status_code == 403
    assert client.get(f"{base}/nodes/{nodes['contratos']}/children").status_code == 403
