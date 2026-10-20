"""M7: the per-folder document list is paginated (spike P1); the default page keeps the array contract."""

import pytest

from app.knowledge.models import Document
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
        for index in range(5):
            session.add(Document(
                organization_id=world.organization_id, workspace_folder_id=world.folders["politicas"],
                external_file_id=f"extra-{index}", name=f"extra-{index}.pdf", mime_type="application/pdf",
                source_url="u", content_hash="c" * 64, processing_version="v1", index_status="indexed"))
    client.cookies.clear()
    login(client, gateway, code="bruno", email="bruno@acme.test", subject="bruno")
    return client, world


def test_documents_are_paginated_with_a_total_header(world_api):
    client, world = world_api
    path = f"/workspace-folders/{world.folders['politicas']}/documents?organization_id={world.organization_id}"
    first = client.get(path + "&page=1&page_size=4")
    assert first.status_code == 200 and len(first.json()) == 4
    assert first.headers["X-Total-Count"] == "6"
    second = client.get(path + "&page=2&page_size=4")
    assert len(second.json()) == 2
    names = [item["name"] for item in first.json() + second.json()]
    assert names == sorted(names) and len(set(names)) == 6


def test_default_page_keeps_the_array_and_caps_the_page_size(world_api):
    client, world = world_api
    path = f"/workspace-folders/{world.folders['politicas']}/documents?organization_id={world.organization_id}"
    assert len(client.get(path).json()) == 6
    assert client.get(path + "&page_size=1000").status_code == 422
    assert client.get(path + "&page=0").status_code == 422
