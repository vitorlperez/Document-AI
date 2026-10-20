"""T-C1: Spaces admin API, owner/manager/member matrix (ADR-0021 D5)."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.audit_usage.models import AuditLog
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    create_organization,
    login,
    search_api,
)
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def base(world, suffix=""):
    return f"/organizations/{world.organization_id}/spaces{suffix}"


def test_owner_creates_renames_archives_and_grants(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "eva")
    created = client.post(base(world), json={"name": "Juridico", "description": "contratos"})
    assert created.status_code == 201
    space_id = created.json()["id"]
    assert client.patch(base(world, f"/{space_id}"), json={"name": "Legal", "description": None}).json()["name"] == "Legal"
    assert client.post(base(world, f"/{space_id}/members"), json={"user_id": str(world.users["ana"])}).status_code == 201
    granted = client.post(base(world, f"/{space_id}/folders/{world.folders['rh']}"), json={"disclosure": {"text_version": "v1"}})
    assert granted.status_code == 201
    assert client.delete(base(world, f"/{space_id}/folders/{world.folders['rh']}")).status_code == 204
    assert client.post(base(world), json={"name": "legal"}).status_code == 409  # duplicate, case-insensitive
    assert client.delete(base(world, f"/{space_id}")).status_code == 204
    listed = {item["name"] for item in client.get(base(world)).json()}
    assert listed == {"Geral", "RH", "Diretoria"}  # admin sees every active Space; archived one is gone


def test_manager_manages_only_their_space(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "ana")  # manager of RH
    assert client.post(base(world, f"/{world.spaces['rh']}/members"),
                       json={"user_id": str(world.users["daniel"])}).status_code == 201
    assert client.post(base(world, f"/{world.spaces['diretoria']}/members"),
                       json={"user_id": str(world.users["bruno"])}).status_code == 404  # cannot even see it
    assert client.post(base(world), json={"name": "Novo"}).status_code == 403
    assert client.post(base(world, f"/{world.spaces['rh']}/folders/{world.folders['diretoria']}"),
                       json={"disclosure": {"text_version": "v1"}}).status_code == 403
    assert client.delete(base(world, f"/{world.spaces['rh']}/members/{world.users['daniel']}")).status_code == 204


def test_member_sees_only_own_spaces_and_cannot_manage(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "bruno")
    assert {item["name"] for item in client.get(base(world)).json()} == {"Geral", "RH"}
    assert all(set(item) >= {"id", "name", "description", "is_default", "member_count", "folder_count", "my_role"}
               for item in client.get(base(world)).json())
    assert client.get(base(world, f"/{world.spaces['rh']}/members")).status_code == 200
    assert client.post(base(world, f"/{world.spaces['rh']}/members"),
                       json={"user_id": str(world.users["daniel"])}).status_code == 403


def test_space_of_others_does_not_exist_for_a_member(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "daniel")
    assert client.get(base(world, f"/{world.spaces['rh']}/members")).status_code == 404
    assert client.get(base(world, f"/{uuid4()}/members")).status_code == 404


def test_user_of_another_organization_gets_404_everywhere(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "outsider")
    create_organization(client)
    assert client.get(base(world)).status_code == 404
    assert client.post(base(world), json={"name": "X"}).status_code == 404
    assert client.get(base(world, f"/{world.spaces['rh']}/members")).status_code == 404


def test_admin_enters_a_space_with_audit_and_then_reads_it(world_api):
    client, factory, gateway, world = world_api
    as_user(client, gateway, "eva")
    folder_url = f"/workspace-folders/{world.folders['diretoria']}/documents?organization_id={world.organization_id}"
    assert client.get(folder_url).json()["readable"] is False
    assert client.post(base(world, f"/{world.spaces['diretoria']}/enter")).status_code == 200
    assert [item["name"] for item in client.get(folder_url).json()] == ["diretoria.pdf"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "space.admin_entered", AuditLog.target_id == world.spaces["diretoria"])) == 1
    as_user(client, gateway, "bruno")
    assert client.post(base(world, f"/{world.spaces['diretoria']}/enter")).status_code in (403, 404)


def test_impact_counts_documents_that_leave_the_persons_reach(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "eva")
    impact = client.get(base(world, f"/{world.spaces['rh']}/members/{world.users['bruno']}/impact")).json()
    assert impact["documents_lost"] == 1  # the RH document; Geral stays reachable
    assert all(isinstance(impact[key], int) and impact[key] >= 0
               for key in ("conversations_hidden", "automations_paused", "followed_queries_cleared"))
    carla = client.get(base(world, f"/{world.spaces['rh']}/members/{world.users['carla']}/impact")).json()
    assert carla["documents_lost"] == 1
