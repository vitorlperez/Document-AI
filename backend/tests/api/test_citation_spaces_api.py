"""T-E2: citations carry the caller's Spaces (answer and history); T-E3 merges one file indexed in two folders."""

import pytest

from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import CiteEverythingProvider, add_shared_copy, remove_from_space
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        shared = add_shared_copy(session, world)
    client.app.state.semantic_provider = CiteEverythingProvider()
    return client, factory, gateway, world, shared


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def ask(client, world, question="qual o reajuste?", **extra):
    return client.post(f"/organizations/{world.organization_id}/questions",
                       json={"question": question, "scope": "selection", "providers": ["google_drive"], **extra})


def seals(body):
    return {c["document_name"]: sorted(s["name"] for s in c["spaces"]) for c in body["citations"]}


def test_answer_citations_carry_the_callers_spaces(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "carla")
    body = ask(client, world).json()
    assert seals(body)["diretoria.pdf"] == ["Diretoria"]
    assert seals(body)["politicas.pdf"] == ["Geral"]


def test_a_file_in_two_folders_is_one_citation_with_both_seals_for_carla_and_only_geral_for_daniel(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "carla")
    carla = ask(client, world).json()
    shared = [c for c in carla["citations"] if c["document_name"] == "ferias-compartilhado.pdf"]
    assert len(shared) == 1 and sorted(s["name"] for s in shared[0]["spaces"]) == ["Geral", "RH"]
    as_user(client, gateway, "daniel")
    daniel = ask(client, world).json()
    shared = [c for c in daniel["citations"] if c["document_name"] == "ferias-compartilhado.pdf"]
    assert len(shared) == 1 and [s["name"] for s in shared[0]["spaces"]] == ["Geral"]
    assert "rh.pdf" not in seals(daniel)


def test_history_recomputes_seals_and_never_trusts_the_stored_ones(world_api):
    client, factory, gateway, world, _ = world_api
    as_user(client, gateway, "carla")
    conversation_id = ask(client, world).json()["conversation_id"]
    with factory.begin() as session:
        from app.knowledge.models import ConversationMessage
        message = session.query(ConversationMessage).filter_by(role="assistant").one()
        forged = dict(message.response)
        forged["citations"] = [{**c, "spaces": [{"id": "x", "name": "Forjado"}]} for c in forged["citations"]]
        message.response = forged
    history = client.get(f"/organizations/{world.organization_id}/conversations/{conversation_id}").json()
    assistant = history["messages"][1]["response"]
    assert "Forjado" not in str(assistant["citations"])
    assert seals(assistant)["diretoria.pdf"] == ["Diretoria"]
