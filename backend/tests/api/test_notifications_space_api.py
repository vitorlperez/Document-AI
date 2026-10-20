"""T-H4: notifications carry provenance and are hidden on read after the person loses access."""

import pytest

from app.knowledge.derived_visibility import HIDDEN_NOTICE, Provenance
from app.notifications.models import Notification
from app.notifications.service import NotificationService
from app.core.scoping import OrganizationScope
from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import remove_from_space
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


def add(factory, world, who, kind, data, body="Segredo salarial do RH"):
    with factory.begin() as session:
        note = Notification(organization_id=world.organization_id, user_id=world.users[who], kind=kind,
                            title="Aviso", body=body, data=data)
        session.add(note)
        session.flush()
        return str(note.id)


def listing(client, world):
    return {item["id"]: item for item in client.get(f"/organizations/{world.organization_id}/notifications").json()["items"]}


def test_notify_stores_provenance_in_data(world_api):
    _, factory, _, world = world_api
    with factory.begin() as session:
        note = NotificationService(session).notify(
            scope=OrganizationScope(world.organization_id), user_id=world.users["carla"], kind="automation_result",
            title="t", body="b", data={"x": 1},
            provenance=Provenance(document_ids=frozenset({world.documents["rh"]}), folder_ids=frozenset({world.folders["rh"]})))
        assert note.data["provenance"] == {"document_ids": [str(world.documents["rh"])],
                                           "workspace_folder_ids": [str(world.folders["rh"])]}
        assert note.data["x"] == 1


def test_item_with_provenance_is_hidden_once_the_folder_is_lost(world_api):
    client, factory, gateway, world = world_api
    prov = {"document_ids": [str(world.documents["rh"])], "workspace_folder_ids": [str(world.folders["rh"])]}
    note_id = add(factory, world, "bruno", "automation_result", {"provenance": prov, "citations": [{"document_id": str(world.documents["rh"])}], "automation_id": "a1"})
    as_user(client, gateway, "bruno")
    assert listing(client, world)[note_id]["body"] == "Segredo salarial do RH"
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    item = listing(client, world)[note_id]
    assert item["body"] == HIDDEN_NOTICE
    assert "citations" not in item["data"] and "provenance" not in item["data"] and item["data"]["hidden"] is True
    assert item["data"]["automation_id"] == "a1"


def test_old_item_without_provenance_uses_its_citations(world_api):
    client, factory, gateway, world = world_api
    note_id = add(factory, world, "bruno", "followed_query_changed", {"citations": [{"document_id": str(world.documents["rh"])}]})
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    assert listing(client, world)[note_id]["body"] == HIDDEN_NOTICE


def test_old_item_with_nothing_is_hidden_only_for_content_kinds_and_only_after_a_loss(world_api):
    client, factory, gateway, world = world_api
    content = add(factory, world, "bruno", "automation_result", {})
    other = add(factory, world, "bruno", "automation_failed", {})
    as_user(client, gateway, "bruno")
    seen = listing(client, world)
    assert seen[content]["body"] == "Segredo salarial do RH" and seen[other]["body"] == "Segredo salarial do RH"
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    seen = listing(client, world)
    assert seen[content]["body"] == HIDDEN_NOTICE and seen[other]["body"] == "Segredo salarial do RH"


def test_items_still_readable_stay_visible(world_api):
    client, factory, gateway, world = world_api
    prov = {"document_ids": [str(world.documents["politicas"])], "workspace_folder_ids": [str(world.folders["politicas"])]}
    note_id = add(factory, world, "bruno", "automation_result", {"provenance": prov})
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    assert listing(client, world)[note_id]["body"] == "Segredo salarial do RH"
