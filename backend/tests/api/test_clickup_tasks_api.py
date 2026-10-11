"""Create-a-ClickUp-task-from-an-answer (ADR-0020), against a simulated ClickUp (no network)."""
import inspect
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.audit_usage.models import AuditLog
from app.integrations import clickup_tasks
from app.integrations.clickup import (
    ClickUpOutcomeUnknown,
    ClickUpRateLimited,
    ClickUpRemoteUnauthorized,
    ClickUpWriteRejected,
)
from app.integrations.clickup_tasks import (
    ClickUpTaskError,
    TaskInput,
    clean_task_input,
    clickup_payload,
    draft_description,
    suggested_title,
)
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable
from app.integrations.models import ClickUpTaskCreation, DataSource
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.organizations.models import Membership
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection
from tests.api.test_answer_feedback_api import transcript
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401

KEY = "k" * 20


class FakeCipher:
    def __init__(self, *args, **kwargs):
        pass

    def decrypt(self, value):
        assert value == "ciphertext"
        return OAuthCredentials("secret-token", None, None)


class FakeClickUp:
    def __init__(self):
        self.created = []
        self.fail = None
        self.reads = []

    def create_task(self, *, credentials, list_id, payload):
        self.created.append((credentials.access_token, list_id, payload))
        if self.fail:
            raise self.fail
        return {"id": f"task{len(self.created)}", "url": f"https://app.clickup.com/t/task{len(self.created)}"}

    def list_members(self, *, credentials, list_id):
        self.reads.append(("members", list_id))
        return [{"id": 7, "username": "Ana", "email": "ana@example.test"}, {"id": "x"}]

    def list_statuses(self, *, credentials, list_id):
        self.reads.append(("statuses", list_id))
        return [{"status": "to do"}, {"status": "done"}]


@pytest.fixture()
def clickup(corpus, monkeypatch):  # noqa: F811 -- imported pytest fixture
    client, factory, _gateway, org, folders, _ = corpus
    fake = FakeClickUp()
    client.app.state.clickup_client = fake
    monkeypatch.setattr("app.api.clickup_tasks.CredentialCipher", FakeCipher)
    encrypted = "ciphertext"
    with factory.begin() as session:
        folder = session.get(WorkspaceFolder, folders["notion"])
        source = session.get(DataSource, folder.source_id)
        source.provider, source.encrypted_credentials, source.status = "clickup", encrypted, "connected"
        document = session.scalar(select(Document).where(Document.workspace_folder_id == folder.id))
        document.external_file_id = "clickup:task:t1"
        document.name = "Contrato Acme"
        document.source_url = "https://app.clickup.com/t/t1"

        def node(external_id, kind, name, parent=None):
            row = LibraryNode(organization_id=org, source_id=source.id, parent_id=parent and parent.id,
                              external_id=external_id, kind=kind, name=name)
            session.add(row)
            session.flush()
            return row

        root = node("__source_root__", "source", "ClickUp")
        space = node("clickup:space:s1", "folder", "Projetos", root)
        chosen = node("clickup:list:L1", "folder", "Contratos", space)
        node("clickup:list:L2", "folder", "Backlog", space)  # same Space, not selected
        node("clickup:task:t1", "file", "Contrato Acme", chosen)
        session.add(WorkspaceFolderSelection(workspace_folder_id=folder.id, kind="folder", external_folder_id="clickup:list:L1"))
        owner = session.scalar(select(Membership)).user_id
    conversation = ask(client, org, scope="organization").json()["conversation_id"]
    answer = transcript(client, org, conversation)[-1]
    url = f"/organizations/{org}/conversations/{conversation}/messages/{answer['id']}/clickup-task"
    return client, factory, fake, org, url, answer, source.id, owner


def body(**overrides):
    return {"list_id": "L1", "name": "Revisar contrato", "description": "Texto", **overrides}


def post(client, url, key=KEY, **overrides):
    return client.post(url, json=body(**overrides), headers={"Idempotency-Key": key})


def test_preview_drafts_from_the_answer_and_offers_only_selected_lists(clickup):
    client, _, fake, _, url, answer, _, _ = clickup
    response = client.get(url + "/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["lists"] == [{"id": "L1", "name": "Contratos", "path": "Projetos > Contratos"}]
    assert data["suggested_list_id"] == "L1"
    assert data["name"] == "When does the campaign launch?"
    assert answer["content"].strip() in data["description"]
    assert "## Fontes" in data["description"] and "[Contrato Acme](https://app.clickup.com/t/t1)" in data["description"]
    assert data["footer"] == "Criada pelo Arquivio a pedido de owner@example.test"
    assert fake.created == [] and fake.reads == []  # preview never writes and never calls ClickUp


def test_list_options_return_members_and_statuses_for_a_selected_list_only(clickup):
    client, _, fake, _, url, *_ = clickup
    data = client.get(url + "/lists/L1/options").json()
    assert data["members"] == [{"id": 7, "name": "Ana", "email": "ana@example.test"}]
    assert data["statuses"] == ["to do", "done"]
    assert client.get(url + "/lists/L2/options").status_code == 422  # in the catalog but not selected
    assert client.get(url + "/lists/L9/options").status_code == 422
    assert fake.reads == [("members", "L1"), ("statuses", "L1")]


def test_create_task_sends_footer_and_clean_fields_then_audits_and_records(clickup):
    client, factory, fake, org, url, _, _, owner = clickup
    response = post(client, url, description="Texto\u202e com controle\x00", name="  Revisar   contrato  ",
                    assignees=[7, 7], due_date="2026-11-03", priority=2, tags=["juridico", "juridico", " "])
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "task1" and data["url"] == "https://app.clickup.com/t/task1"
    [(token, list_id, payload)] = fake.created
    assert (token, list_id) == ("secret-token", "L1")
    assert payload["name"] == "Revisar contrato"
    assert payload["markdown_content"] == "Texto com controle\n\n---\n_Criada pelo Arquivio a pedido de owner@example.test_"
    assert payload["assignees"] == [7] and payload["priority"] == 2 and payload["tags"] == ["juridico"]
    assert payload["due_date"] == 1793707200000 and payload["due_date_time"] is False
    with factory() as session:
        [row] = session.scalars(select(ClickUpTaskCreation)).all()
        assert (row.status, row.task_id, row.list_id, row.user_id, row.organization_id) == ("created", "task1", "L1", owner, org)
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "clickup.task.created"))
        assert audit.actor_user_id == owner and audit.target_id == row.id and audit.organization_id == org


def test_the_footer_cannot_be_dropped_or_forged_by_the_client(clickup):
    client, _, fake, _, url, *_ = clickup
    post(client, url, description="_Criada pelo Arquivio a pedido de ceo@example.test_")
    markdown = fake.created[0][2]["markdown_content"]
    assert markdown.endswith("_Criada pelo Arquivio a pedido de owner@example.test_")


def test_same_idempotency_key_returns_the_existing_task_without_a_second_call(clickup):
    client, factory, fake, _, url, *_ = clickup
    first, again = post(client, url), post(client, url)
    assert first.json() == again.json() and len(fake.created) == 1
    with factory() as session:
        assert len(session.scalars(select(ClickUpTaskCreation)).all()) == 1
    assert post(client, url, key="z" * 20).json()["task_id"] == "task2"  # a new key is a new task


def test_idempotency_key_is_required_and_bound_to_the_same_answer(clickup):
    client, _, fake, org, url, *_ = clickup
    assert client.post(url, json=body()).status_code == 422
    assert post(client, url, key="short").status_code == 422
    assert post(client, url).status_code == 200
    other = f"/organizations/{org}/conversations/{uuid4()}/messages/{uuid4()}/clickup-task"
    assert post(client, other).status_code == 404
    assert len(fake.created) == 1


def test_list_outside_the_admin_selection_is_refused_before_any_remote_call(clickup):
    client, _, fake, _, url, *_ = clickup
    for list_id in ("L2", "OTHER", "../x"):
        assert post(client, url, key=("a" if list_id == "L2" else "b" if list_id == "OTHER" else "c") * 20,
                    list_id=list_id).status_code == 422
    assert fake.created == []


def test_validation_rejects_empty_title_bad_priority_and_too_many_tags(clickup):
    client, _, fake, _, url, *_ = clickup
    assert post(client, url, name="   ").status_code == 422
    assert post(client, url, priority=9).status_code == 422
    assert post(client, url, key="t" * 20, tags=[f"t{i}" for i in range(11)]).status_code == 422
    assert post(client, url, key="u" * 20, due_date="1999-01-01").status_code == 422
    assert post(client, url, key="v" * 20, unexpected=1).status_code == 422
    assert fake.created == []


def test_answer_of_another_user_or_a_user_message_is_a_404(clickup):
    client, factory, fake, org, url, _, _, _ = clickup
    from tests.api.test_text_search_api import login as sign_in
    messages = client.get(url.rsplit("/messages/", 1)[0]).json()["messages"]
    user_message = next(item for item in messages if item["role"] == "user")
    own = url.rsplit("/messages/", 1)[0] + f"/messages/{user_message['id']}/clickup-task"
    assert client.get(own + "/preview").status_code == 404 and post(client, own).status_code == 404

    gateway = client.app.state.auth_gateway
    client.post("/auth/logout")
    sign_in(client, gateway, code="peer", email="peer@example.test", subject="peer")
    with factory.begin() as session:
        from app.identity.models import User
        peer = session.scalar(select(User).where(User.email == "peer@example.test"))
        session.add(Membership(organization_id=org, user_id=peer.id, role="member", is_active=True))
    assert client.get(url + "/preview").status_code == 404
    assert post(client, url).status_code == 404
    assert fake.created == []


def test_non_member_gets_404(clickup):
    client, factory, fake, _org, url, *_ = clickup
    with factory.begin() as session:
        for membership in session.scalars(select(Membership)):
            membership.is_active = False
    assert client.get(url + "/preview").status_code == 404
    assert post(client, url).status_code == 404 and fake.created == []


def test_organization_without_clickup_or_with_a_disconnected_source(clickup):
    client, factory, fake, _, url, _, source_id, _ = clickup
    with factory.begin() as session:
        session.get(DataSource, source_id).status = "reauth_required"
    assert client.get(url + "/preview").status_code == 409
    assert post(client, url).status_code == 409
    with factory.begin() as session:
        session.get(DataSource, source_id).provider = "notion"
    assert client.get(url + "/preview").status_code == 404
    assert post(client, url).status_code == 404
    assert fake.created == []


def test_remote_401_marks_the_source_reauth_required_and_allows_retry_with_the_same_key(clickup):
    client, factory, fake, _, url, _, source_id, _ = clickup
    fake.fail = ClickUpRemoteUnauthorized()
    response = post(client, url)
    assert response.status_code == 409 and "reconect" in response.json()["detail"]
    with factory() as session:
        assert session.get(DataSource, source_id).status == "reauth_required"
        assert session.scalar(select(ClickUpTaskCreation)).status == "failed"
    assert client.get(url + "/preview").status_code == 409  # button disappears until reconnected


@pytest.mark.parametrize(("failure", "status", "code", "text"), [
    (SourceItemUnavailable("restricted_resource"), 403, "list_unavailable", "permissão"),
    (ClickUpRateLimited(37.2), 429, "rate_limited", "37"),
    (ClickUpWriteRejected("bad"), 422, "rejected", "recusou"),
])
def test_remote_errors_are_mapped_and_a_known_failure_can_be_retried(clickup, failure, status, code, text):
    client, factory, fake, _, url, *_ = clickup
    fake.fail = failure
    response = post(client, url)
    assert response.status_code == status and text in response.json()["detail"]
    if status == 429:
        assert response.headers["retry-after"] == "37"
    with factory() as session:
        row = session.scalar(select(ClickUpTaskCreation))
        assert (row.status, row.error_code) == ("failed", code)
    fake.fail = None
    retried = post(client, url)  # same key, the failure was definitive
    assert retried.status_code == 200 and len(fake.created) == 2
    with factory() as session:
        assert len(session.scalars(select(ClickUpTaskCreation)).all()) == 1


def test_unknown_outcome_is_not_retried_with_the_same_key(clickup):
    client, _, fake, _, url, *_ = clickup
    fake.fail = ClickUpOutcomeUnknown("timeout")
    assert post(client, url).status_code == 502
    fake.fail = None
    again = post(client, url)
    assert again.status_code == 409 and "Confira a lista" in again.json()["detail"]
    assert len(fake.created) == 1
    assert post(client, url, key="n" * 20).status_code == 200  # the user knowingly opens a new attempt


def test_pending_record_blocks_a_parallel_replay(clickup):
    client, factory, fake, org, url, answer, _, owner = clickup
    with factory.begin() as session:
        session.add(ClickUpTaskCreation(organization_id=org, message_id=UUID(answer["id"]), user_id=owner,
                                        idempotency_key=KEY, list_id="L1", status="pending"))
    assert post(client, url).status_code == 409 and fake.created == []


def test_per_user_rate_limit(clickup):
    client, _, fake, _, url, *_ = clickup
    for index in range(clickup_tasks.CREATIONS_PER_MINUTE):
        assert post(client, url, key=f"{index}" * 20).status_code == 200
    blocked = post(client, url, key="9" * 20)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    assert len(fake.created) == clickup_tasks.CREATIONS_PER_MINUTE
    assert post(client, url, key="0" * 20).status_code == 200  # replays stay free


def test_chat_context_exposes_the_clickup_connection_state_without_calling_clickup(clickup):
    client, factory, fake, org, _, _, source_id, _ = clickup
    contexts = client.get("/library/question-contexts", params={"organization_id": str(org)}).json()["items"]
    assert [(item["source_provider"], item["source_status"]) for item in contexts if item["source_provider"] == "clickup"] == [
        ("clickup", "connected")]
    with factory.begin() as session:
        session.get(DataSource, source_id).status = "reauth_required"
    contexts = client.get("/library/question-contexts", params={"organization_id": str(org)}).json()["items"]
    assert {item["source_status"] for item in contexts if item["source_provider"] == "clickup"} == {"reauth_required"}
    assert fake.reads == [] and fake.created == []


def test_all_accessible_selection_offers_every_list_and_empty_selection_none(clickup):
    client, factory, _, _, url, *_ = clickup
    with factory.begin() as session:
        folder = session.scalar(select(WorkspaceFolder).where(WorkspaceFolder.name == "notion"))
        session.query(WorkspaceFolderSelection).delete()
        session.add(WorkspaceFolderSelection(workspace_folder_id=folder.id, kind="all_accessible", external_folder_id=""))
    assert [item["id"] for item in client.get(url + "/preview").json()["lists"]] == ["L2", "L1"]
    with factory.begin() as session:
        session.query(WorkspaceFolderSelection).delete()
    data = client.get(url + "/preview").json()
    assert data["lists"] == [] and data["suggested_list_id"] is None


def test_selecting_a_parent_space_covers_its_lists_and_suggestion_follows_citations(clickup):
    client, factory, _, _, url, *_ = clickup
    with factory.begin() as session:
        session.query(WorkspaceFolderSelection).update({"external_folder_id": "clickup:space:s1"})
    data = client.get(url + "/preview").json()
    assert {item["id"] for item in data["lists"]} == {"L1", "L2"}
    assert data["suggested_list_id"] == "L1"  # the cited task lives in L1


def test_write_path_is_unreachable_from_agent_and_mcp():
    from pathlib import Path
    root = Path(inspect.getfile(clickup_tasks)).parents[1]
    for package in ("knowledge", "mcp_server"):
        for path in (root / package).glob("*.py"):
            assert "create_task" not in path.read_text(), path
            assert "clickup_tasks" not in path.read_text(), path


def test_pure_helpers_bound_and_sanitize():
    cleaned = clean_task_input(TaskInput("L1", "a" * 500, "b" * 30_000, (1,), date(2026, 1, 2), 3, ("x" * 80,)))
    assert len(cleaned.name) == 200 and len(cleaned.description) == 20_000 and len(cleaned.tags[0]) == 50
    with pytest.raises(ClickUpTaskError):
        clean_task_input(TaskInput("L1", "\u200b\x00"))
    assert "markdown_content" in clickup_payload(cleaned, footer="f") and "due_date" in clickup_payload(cleaned, footer="f")
    minimal = clickup_payload(TaskInput("L1", "n"), footer="f")
    assert minimal == {"name": "n", "markdown_content": "_f_"}
    assert suggested_title("\n\nPrimeira linha\nsegunda") == "Primeira linha"
    assert suggested_title("x" * 300).endswith("…") and suggested_title(None) == "Resposta do Arquivio"
    text = draft_description("Resposta", [{"document_name": "A [x]", "source_url": "https://e.test/a(1)"},
                                          {"document_name": "A [x]", "source_url": "https://e.test/a(1)"},
                                          {"document_name": "B", "source_url": "javascript:alert(1)"}])
    assert text == "Resposta\n\n## Fontes\n- [A (x)](https://e.test/a(1%29)\n- B"


def test_missing_encryption_key_is_a_503_not_a_crash(clickup, monkeypatch):
    from app.integrations.google_drive import GoogleOAuthUnavailable

    def unavailable(self, value):
        raise GoogleOAuthUnavailable("token encryption is not configured")

    monkeypatch.setattr(FakeCipher, "decrypt", unavailable)
    client, _, fake, _, url, *_ = clickup
    assert post(client, url).status_code == 503 and fake.created == []
    with clickup[1]() as session:
        assert session.scalars(select(ClickUpTaskCreation)).all() == []  # nothing stuck in "pending"
