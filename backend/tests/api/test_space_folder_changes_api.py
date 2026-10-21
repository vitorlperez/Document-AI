"""PUT /organizations/{id}/spaces/{id}/folders: grant/revoke diff in one transaction (aba Pastas do Espaço)."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.audit_usage.models import AuditLog
from app.spaces.models import SpaceFolderGrant
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    login,
    search_api,
)
from tests.spaces_helpers import bind_login_identities, seed_world

DISCLOSURE = {"text_version": "v1"}


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


def url(world, space="diretoria"):
    return f"/organizations/{world.organization_id}/spaces/{world.spaces[space]}/folders"


def active_folders(factory, world, space="diretoria"):
    with factory() as session:
        return set(session.scalars(select(SpaceFolderGrant.workspace_folder_id).where(
            SpaceFolderGrant.space_id == world.spaces[space], SpaceFolderGrant.revoked_at.is_(None))))


def test_admin_applies_a_diff_and_it_is_idempotent(world_api):
    client, factory, gateway, world = world_api
    as_user(client, gateway, "eva")
    before = active_folders(factory, world)
    body = {"grant": [str(world.folders["rh"]), str(world.folders["politicas"])],
            "revoke": [str(world.folders["diretoria"])], "disclosure": DISCLOSURE}
    first = client.put(url(world), json=body)
    assert first.status_code == 200
    assert set(first.json()["granted"]) == {str(world.folders["rh"]), str(world.folders["politicas"])}
    assert first.json()["revoked"] == [str(world.folders["diretoria"])]
    after = active_folders(factory, world)
    assert after == {world.folders["rh"], world.folders["politicas"]} and before == {world.folders["diretoria"]}
    again = client.put(url(world), json=body)
    assert again.status_code == 200 and again.json() == {"granted": [], "revoked": []}
    assert active_folders(factory, world) == after
    with factory() as session:
        audited = session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action.in_(["space.folder_granted", "space.folder_revoked"])))
    assert audited >= 6  # 2 grants + 1 revoke, two audit rows each (space + folder)


def test_only_org_admin_can_change_folders(world_api):
    client, factory, gateway, world = world_api
    body = {"grant": [str(world.folders["rh"])], "revoke": [], "disclosure": DISCLOSURE}
    for who in ("ana", "carla"):  # manager of RH / member of Diretoria
        as_user(client, gateway, who)
        assert client.put(url(world, "rh"), json=body).status_code == 403
    as_user(client, gateway, "daniel")  # cannot see RH at all
    assert client.put(url(world, "rh"), json=body).status_code in (403, 404)
    assert active_folders(factory, world, "rh") == {world.folders["rh"]}


def test_folder_of_another_organization_fails_the_whole_batch(world_api):
    client, factory, gateway, world = world_api
    as_user(client, gateway, "eva")
    before = active_folders(factory, world)
    body = {"grant": [str(world.folders["rh"]), str(uuid4())], "revoke": [str(world.folders["diretoria"])],
            "disclosure": DISCLOSURE}
    assert client.put(url(world), json=body).status_code == 403
    assert active_folders(factory, world) == before  # atomic: nothing applied


def test_grant_requires_disclosure_and_unknown_space_is_404(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "eva")
    assert client.put(url(world), json={"grant": [str(world.folders["rh"])], "revoke": []}).status_code == 422
    assert client.put(url(world), json={"grant": [], "revoke": []}).status_code == 200
    missing = f"/organizations/{world.organization_id}/spaces/{uuid4()}/folders"
    assert client.put(missing, json={"grant": [], "revoke": []}).status_code == 404


def test_folder_listing_tells_which_tool_and_account_each_folder_belongs_to(world_api):
    client, factory, gateway, world = world_api
    from app.integrations.models import DataSource

    with factory.begin() as session:
        session.get(DataSource, world.source_id).account_email = "conta@acme.test"
    as_user(client, gateway, "eva")
    rows = client.get(f"/workspace-folders?organization_id={world.organization_id}").json()
    assert rows and all(row["source_provider"] == "google_drive" and row["source_account"] == "conta@acme.test" for row in rows)
    as_user(client, gateway, "bruno")  # a member sees the tool, never the connected account
    rows = client.get(f"/workspace-folders?organization_id={world.organization_id}").json()
    assert rows and all(row["source_provider"] == "google_drive" and row["source_account"] is None for row in rows)
