"""T-C3: the Space filter flows from the question payload to the resolver and only narrows."""

import dataclasses

import pytest

from app.knowledge.agent import AgentRequest
from app.spaces.filter import current_space_filter, narrowed_to_spaces
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    FakeSemanticProvider,
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
    client.app.state.semantic_provider = FakeSemanticProvider()
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def ask(client, world, **extra):
    return client.post(
        f"/organizations/{world.organization_id}/questions",
        json={"question": "qual a politica?", "scope": "selection", "providers": ["google_drive"], **extra})


def test_question_contexts_carry_spaces_and_accept_the_filter(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    items = client.get(f"/library/question-contexts?organization_id={world.organization_id}").json()["items"]
    assert {item["name"]: [s["name"] for s in item["spaces"]] for item in items} == {
        "politicas": ["Geral"], "rh": ["RH"], "diretoria": ["Diretoria"]}
    narrowed = client.get(
        f"/library/question-contexts?organization_id={world.organization_id}&space_ids={world.spaces['rh']}").json()
    assert [item["name"] for item in narrowed["items"]] == ["rh"]
    assert client.get(f"/library/question-contexts?organization_id={world.organization_id}"
                      f"&space_ids={world.spaces['rh']}&space_ids={world.spaces['geral']}").status_code == 200


def test_question_without_filter_searches_the_union(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    response = ask(client, world)
    assert response.status_code == 200
    assert response.json()["resolved_context"]["folder_count"] == 3


def test_question_with_space_filter_only_narrows(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    response = ask(client, world, space_ids=[str(world.spaces["rh"])])
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_context"]["folder_count"] == 1
    assert {c["document_id"] for c in body["citations"]} <= {str(world.documents["rh"])}


def test_foreign_space_id_is_404_not_403(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "bruno")
    response = ask(client, world, space_ids=[str(world.spaces["diretoria"])])
    assert response.status_code == 404 and response.json() == {"detail": "space not found"}
    assert client.get(f"/library/question-contexts?organization_id={world.organization_id}"
                      f"&space_ids={world.spaces['diretoria']}").status_code == 404


def test_history_records_the_requested_filter_but_it_never_authorizes(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    body = ask(client, world, space_ids=[str(world.spaces["rh"])]).json()
    history = client.get(
        f"/organizations/{world.organization_id}/conversations/{body['conversation_id']}").json()
    user_message = next(m for m in history["messages"] if m["role"] == "user")
    assert user_message["context"]["space_ids"] == [str(world.spaces["rh"])]


def test_filter_context_is_scoped_and_restores():
    assert current_space_filter() is None
    with narrowed_to_spaces(None):
        assert current_space_filter() is None
    with narrowed_to_spaces([]):
        assert current_space_filter() == frozenset()
    assert current_space_filter() is None


def test_agent_request_owns_the_filter_not_the_model():
    assert "space_ids" in {f.name for f in dataclasses.fields(AgentRequest)}
