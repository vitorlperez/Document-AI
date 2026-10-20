"""T-C2: GET /workspace-folders is Space-aware; admins get operational metadata without file names."""

import pytest

from app.integrations.models import DataSource
from app.workspaces.models import WorkspaceFolder
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
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
        source = session.get(DataSource, world.source_id)
        orphan = WorkspaceFolder(organization_id=world.organization_id, source_id=source.id,
                                 external_folder_id="sem-espaco", name="sem-espaco",
                                 uniform_access_confirmed=True, status="ready")
        session.add(orphan)
        session.flush()
        orphan_id = orphan.id
    return client, gateway, world, orphan_id


def listing(client, gateway, world, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)
    response = client.get(f"/workspace-folders?organization_id={world.organization_id}")
    assert response.status_code == 200
    return response, {item["name"]: item for item in response.json()}


def test_member_lists_only_reachable_folders_with_own_space_badges(world_api):
    client, gateway, world, _ = world_api
    _, folders = listing(client, gateway, world, "bruno")
    assert set(folders) == {"politicas", "rh"}
    assert [s["name"] for s in folders["rh"]["spaces"]] == ["RH"]
    assert folders["rh"]["readable"] is True


def test_admin_sees_every_folder_with_all_spaces_and_a_readable_flag(world_api):
    client, gateway, world, orphan_id = world_api
    response, folders = listing(client, gateway, world, "eva")  # owner, member of Geral only
    assert set(folders) == {"politicas", "rh", "diretoria", "sem-espaco"}
    assert {name: item["readable"] for name, item in folders.items()} == {
        "politicas": True, "rh": False, "diretoria": False, "sem-espaco": False}
    assert [s["name"] for s in folders["rh"]["spaces"]] == ["RH"]  # configuration, not content
    assert folders["sem-espaco"]["spaces"] == [] and folders["sem-espaco"]["id"] == str(orphan_id)
    assert ".pdf" not in response.text  # no file names in the operational view


def test_admin_badges_include_every_space_granting_the_folder(world_api):
    client, gateway, world, _ = world_api
    from app.spaces.models import SpaceFolderGrant
    factory = client.app.state.session_factory
    with factory.begin() as session:
        session.add(SpaceFolderGrant(organization_id=world.organization_id, space_id=world.spaces["diretoria"],
                                     workspace_folder_id=world.folders["rh"], disclosure={"text_version": "v1"}))
    _, admin_view = listing(client, gateway, world, "eva")
    assert [s["name"] for s in admin_view["rh"]["spaces"]] == ["Diretoria", "RH"]
    _, bruno_view = listing(client, gateway, world, "bruno")
    assert [s["name"] for s in bruno_view["rh"]["spaces"]] == ["RH"]  # Diretoria is not his to know


def test_organization_without_spaces_keeps_the_legacy_listing(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session, mode="off")
        bind_login_identities(session, world)
    _, folders = listing(client, gateway, world, "daniel")
    assert set(folders) == {"politicas", "rh", "diretoria"}
