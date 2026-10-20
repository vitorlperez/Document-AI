"""T-H1/T-H5: stored answers that cite content the person lost are hidden on read, in history, export and ClickUp."""

import pytest

from app.knowledge.derived_visibility import HIDDEN_NOTICE
from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import CiteEverythingProvider, add_shared_copy, remove_from_space
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
    client.app.state.semantic_provider = CiteEverythingProvider()
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def ask_as(client, gateway, world, who, question="qual o contrato?", conversation_id=None):
    as_user(client, gateway, who)
    body = client.post(f"/organizations/{world.organization_id}/questions", json={
        "question": question, "scope": "selection", "providers": ["google_drive"],
        **({"conversation_id": conversation_id} if conversation_id else {})}).json()
    return body["conversation_id"]


def history(client, world, conversation_id):
    return client.get(f"/organizations/{world.organization_id}/conversations/{conversation_id}").json()


def test_history_hides_answers_citing_a_scope_the_user_lost(world_api):
    client, factory, gateway, world = world_api
    conversation_id = ask_as(client, gateway, world, "bruno")
    before = history(client, world, conversation_id)
    assert before["messages"][1]["content"] != HIDDEN_NOTICE
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    after = history(client, world, conversation_id)
    assert after["messages"][0]["content"] == "qual o contrato?"
    # the answer cited politicas (Geral) and rh (RH): losing RH hides the whole message
    assert after["messages"][1]["content"] == HIDDEN_NOTICE
    assert after["messages"][1]["response"] == {"hidden": True, "reason": "access_changed"}
    assert "rh.pdf" not in str(after["messages"][1]) and "salarial" not in str(after["messages"][1])


def test_history_keeps_answers_whose_sources_are_all_still_accessible(world_api):
    client, factory, gateway, world = world_api
    conversation_id = ask_as(client, gateway, world, "carla")
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")  # someone else's loss
    as_user(client, gateway, "carla")
    kept = history(client, world, conversation_id)["messages"][1]
    assert kept["content"] != HIDDEN_NOTICE and kept["response"]["citations"]


def test_message_without_citations_is_never_hidden(world_api):
    client, factory, gateway, world = world_api
    conversation_id = ask_as(client, gateway, world, "daniel", question="zzzz qqqq xxxx sem relacao")
    with factory.begin() as session:
        from app.knowledge.models import ConversationMessage
        message = session.query(ConversationMessage).filter_by(role="assistant").one()
        message.response = {"answer": "oi", "citations": []}
        message.context = {}
    as_user(client, gateway, "daniel")
    assert history(client, world, conversation_id)["messages"][1]["content"] != HIDDEN_NOTICE


def test_hiding_is_a_read_view_the_stored_message_is_untouched(world_api):
    client, factory, gateway, world = world_api
    conversation_id = ask_as(client, gateway, world, "bruno")
    with factory.begin() as session:
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    history(client, world, conversation_id)
    with factory.begin() as session:
        from app.knowledge.models import ConversationMessage
        stored = session.query(ConversationMessage).filter_by(role="assistant").one()
        assert stored.content != HIDDEN_NOTICE and stored.response["citations"]


def test_a_file_still_reachable_through_another_folder_keeps_the_answer_visible(world_api):
    client, factory, gateway, world = world_api
    with factory.begin() as session:
        shared = add_shared_copy(session, world, folder_keys=("politicas", "rh"))
    conversation_id = ask_as(client, gateway, world, "bruno", question="calendario compartilhado de ferias")
    with factory.begin() as session:  # the only RH-sourced citation is the RH copy of a file also in Geral
        from app.knowledge.models import ConversationMessage
        message = session.query(ConversationMessage).filter_by(role="assistant").one()
        message.response = {**message.response, "citations": [
            {**message.response["citations"][0], "document_id": str(shared["rh"])}]}
        message.context = {}
        remove_from_space(session, world, "bruno", "rh")
    as_user(client, gateway, "bruno")
    assert history(client, world, conversation_id)["messages"][1]["content"] != HIDDEN_NOTICE


def test_history_costs_a_constant_number_of_queries(world_api):
    client, factory, gateway, world = world_api
    conversation_id = ask_as(client, gateway, world, "carla")
    for _ in range(4):
        ask_as(client, gateway, world, "carla", conversation_id=conversation_id)
    from sqlalchemy import event
    engine = factory.kw["bind"]
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, statement, *rest: statements.append(statement))
    as_user(client, gateway, "carla")
    statements.clear()
    body = history(client, world, conversation_id)
    assert len(body["messages"]) == 10
    assert len(statements) <= 40  # bounded; the hiding adds a fixed handful of queries, not one per answer
    first = len(statements)
    for _ in range(3):
        ask_as(client, gateway, world, "carla", conversation_id=conversation_id)
    as_user(client, gateway, "carla")
    statements.clear()
    assert len(history(client, world, conversation_id)["messages"]) == 12
    assert len(statements) <= first + 2
