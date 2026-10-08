# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import User, UserSession
from app.integrations.clickup import (
    CLICKUP_PROCESSING_VERSION,
    ClickUpAccessDenied,
    ClickUpConnectionService,
    ClickUpDocumentProvider,
    ClickUpOAuthClient,
    ClickUpOAuthInvalid,
    ClickUpOAuthUnavailable,
    ClickUpRemoteUnauthorized,
    _doc_text,
    _task_text,
)
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable
from app.integrations.models import DataSource, OAuthConnectionState
from app.integrations.registry import IntegrationRegistry
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.organizations.models import Membership, MembershipRole, Organization
from tests.sync_helpers import T0, seed, session, space  # noqa: F401

DB = "postgresql+psycopg://u:p@localhost/db"
CREDENTIALS = OAuthCredentials("token", None, None)
EDITED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
EDITED_MS = str(int(EDITED.timestamp() * 1000))


class Selection:
    def __init__(self, kind: str, external_folder_id: str = "") -> None:
        self.kind, self.external_folder_id = kind, external_folder_id


class Cipher:
    def decrypt(self, value: str) -> OAuthCredentials:
        return CREDENTIALS


class FakeClient:
    """One workspace: Space > (Folder > List A) and a folderless List B, plus two Docs."""

    def __init__(self, *, docs_error: type[Exception] | None = None) -> None:
        self.task_reads: list[tuple[str, bool]] = []
        self.page_reads: list[str] = []
        self.docs_error = docs_error
        self.tasks = {
            "A": [{"id": "t1", "name": "Contrato Acme", "url": "https://app.clickup.com/t/t1",
                   "date_updated": EDITED_MS, "status": {"status": "em andamento"},
                   "priority": {"priority": "high"}, "assignees": [{"username": "Ana"}],
                   "tags": [{"name": "juridico"}], "due_date": EDITED_MS,
                   "markdown_description": "Cláusula de reajuste anual."},
                  {"id": "t2", "name": "Revisar minuta", "url": "https://app.clickup.com/t/t2",
                   "date_updated": EDITED_MS, "parent": "t1", "description": "Subtarefa"}],
            "B": [{"id": "t3", "name": "Sem descrição", "date_updated": EDITED_MS}],
        }

    def workspaces(self, *, credentials):
        return [{"id": "w1", "name": "Acme"}]

    def spaces(self, *, credentials, workspace_id):
        return [{"id": "s1", "name": "Projetos"}]

    def folders(self, *, credentials, space_id):
        return [{"id": "f1", "name": "Clientes", "lists": [{"id": "A", "name": "Contratos"}]}]

    def folderless_lists(self, *, credentials, space_id):
        return [{"id": "B", "name": "Backlog"}]

    def list_tasks(self, *, credentials, list_id, include_closed):
        self.task_reads.append((list_id, include_closed))
        return self.tasks[list_id]

    def workspace_docs(self, *, credentials, workspace_id):
        if self.docs_error:
            raise self.docs_error("restricted_resource")
        return [{"id": "d1", "name": "Playbook", "date_updated": EDITED_MS, "parent": {"id": "f1", "type": 5}},
                {"id": "d2", "name": "Wiki geral", "date_updated": EDITED_MS, "parent": {"id": "w1", "type": 12}}]

    def doc_pages(self, *, credentials, workspace_id, doc_id):
        self.page_reads.append(doc_id)
        return [{"name": "Onboarding", "content": "Passo a passo", "pages": [
            {"name": "Acessos", "content": "Peça acesso ao ClickUp"}]}]


def discover(client=None, selections=None, **kwargs):
    client = client or FakeClient()
    result = ClickUpDocumentProvider(client, Cipher(), **kwargs.pop("provider", {})).discover(
        encrypted_credentials="encrypted", selections=selections or [Selection("all_accessible")], **kwargs)
    return client, result


def ids(documents):
    return [item.external_file_id for item in documents]


def test_clickup_requires_oauth_configuration() -> None:
    with pytest.raises(ClickUpOAuthUnavailable):
        ClickUpOAuthClient(client_id=None, client_secret=None, redirect_uri=None).authorization_url(state="s")


def test_clickup_authorization_url_carries_client_redirect_and_state() -> None:
    url = ClickUpOAuthClient(client_id="cid", client_secret="sec", redirect_uri="https://api.test/cb").authorization_url(state="st")
    assert url.startswith("https://app.clickup.com/api?")
    assert "client_id=cid" in url and "state=st" in url and "redirect_uri=https%3A%2F%2Fapi.test%2Fcb" in url
    assert "sec" not in url


def test_clickup_exchange_code_returns_a_non_expiring_token_and_maps_failures(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="cid", client_secret="sec", redirect_uri="https://cb")
    request = httpx.Request("POST", "https://api.clickup.com/api/v2/oauth/token")
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer"}, request=request)

    monkeypatch.setattr(httpx, "post", post)
    credentials = client.exchange_code(code="the-code")
    assert (credentials.access_token, credentials.refresh_token, credentials.expires_at) == ("tok", None, None)
    assert sent["json"] == {"client_id": "cid", "client_secret": "sec", "code": "the-code"}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(400, json={}, request=request))
    with pytest.raises(ClickUpOAuthInvalid):
        client.exchange_code(code="bad")


def test_clickup_client_uses_bearer_header_and_normalizes_the_account_email(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    seen = {}

    def get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json={"user": {"email": " Owner@Example.Test "}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    assert client.account_email(credentials=CREDENTIALS) == "owner@example.test"
    assert seen["url"] == "https://api.clickup.com/api/v2/user"
    assert seen["headers"] == {"Authorization": "Bearer token"}


def test_clickup_401_is_auth_and_403_404_are_item_failures(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    for status, expected in ((401, ClickUpRemoteUnauthorized), (403, SourceItemUnavailable), (404, SourceItemUnavailable)):
        monkeypatch.setattr(httpx, "get", lambda url, status=status, **kw: httpx.Response(
            status, json={}, request=httpx.Request("GET", url)))
        with pytest.raises(expected):
            client._request("GET", "/api/v2/team", credentials=CREDENTIALS)


def test_clickup_list_tasks_paginates_until_last_page_and_requests_markdown(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    pages = iter([{"tasks": [{"id": "1"}], "last_page": False}, {"tasks": [{"id": "2"}], "last_page": True}])
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return httpx.Response(200, json=next(pages), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    tasks = client.list_tasks(credentials=CREDENTIALS, list_id="L", include_closed=False)
    assert [task["id"] for task in tasks] == ["1", "2"]
    assert [call["page"] for call in calls] == ["0", "1"]
    assert calls[0]["include_closed"] == "false" and calls[0]["include_markdown_description"] == "true"
    assert calls[0]["archived"] == "false" and calls[0]["subtasks"] == "true"


def test_clickup_docs_are_paginated_by_cursor(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    replies = iter([{"docs": [{"id": "a"}], "next_cursor": "c2"}, {"docs": [{"id": "b"}], "next_cursor": ""}])
    cursors = []

    def get(url, **kwargs):
        cursors.append(kwargs["params"].get("cursor"))
        return httpx.Response(200, json=next(replies), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    assert [doc["id"] for doc in client.workspace_docs(credentials=CREDENTIALS, workspace_id="w")] == ["a", "b"]
    assert cursors == [None, "c2"]


def test_clickup_catalog_builds_the_workspace_space_folder_list_tree() -> None:
    folders = ClickUpDocumentProvider(FakeClient(), Cipher()).folders(encrypted_credentials="x")
    by_id = {item.id: item for item in folders}
    assert by_id["clickup:list:A"].parent_ids == ("clickup:folder:f1",)
    assert by_id["clickup:list:B"].parent_ids == ("clickup:space:s1",)
    assert by_id["clickup:folder:f1"].parent_ids == ("clickup:space:s1",)
    assert by_id["clickup:space:s1"].parent_ids == ("clickup:workspace:w1",)
    assert by_id["clickup:workspace:w1"].kind == "workspace" and by_id["clickup:workspace:w1"].parent_ids == ()


def test_clickup_selected_folder_indexes_only_its_descendants() -> None:
    client, result = discover(selections=[Selection("folder", "clickup:folder:f1")])
    assert ids(result.documents) == ["clickup:doc:d1", "clickup:task:t1", "clickup:task:t2"]
    assert [read[0] for read in client.task_reads] == ["A"]
    assert client.page_reads == ["d1"]  # the workspace-level Doc is outside the selected folder
    task = next(item for item in result.documents if item.external_file_id == "clickup:task:t1")
    assert task.parent_ids == ("clickup:list:A",) and task.mime_type == "text/markdown"
    assert task.processing_version == CLICKUP_PROCESSING_VERSION and task.modified_at == EDITED
    assert task.source_url == "https://app.clickup.com/t/t1"
    doc = next(item for item in result.documents if item.external_file_id == "clickup:doc:d1")
    assert doc.parent_ids == ("clickup:folder:f1",)
    assert doc.source_url == "https://app.clickup.com/w1/v/dc/d1"


def test_clickup_all_accessible_reads_every_list_and_workspace_docs() -> None:
    _, result = discover()
    assert ids(result.documents) == ["clickup:doc:d1", "clickup:doc:d2", "clickup:task:t1", "clickup:task:t2",
                                     "clickup:task:t3"]
    assert result.full_snapshot is True and result.removed_file_ids == ()
    doc2 = next(item for item in result.documents if item.external_file_id == "clickup:doc:d2")
    assert doc2.parent_ids == ("clickup:workspace:w1",)


def test_clickup_closed_tasks_are_excluded_unless_enabled() -> None:
    client, _ = discover()
    assert {include for _, include in client.task_reads} == {False}
    client, _ = discover(provider={"include_closed_tasks": True})
    assert {include for _, include in client.task_reads} == {True}


def test_clickup_task_text_carries_searchable_facts_and_resolves_the_parent_name() -> None:
    _, result = discover()
    by_id = {item.external_file_id: item for item in result.documents}
    text = by_id["clickup:task:t1"].text
    for fragment in ("# Contrato Acme", "Lista: Acme > Projetos > Clientes > Contratos", "Status: em andamento",
                     "Prioridade: high", "Responsáveis: Ana", "Etiquetas: juridico", "Vencimento: 2026-10-01",
                     "Cláusula de reajuste anual."):
        assert fragment in text
    assert "Subtarefa de: Contrato Acme" in by_id["clickup:task:t2"].text


def test_clickup_custom_fields_keep_simple_values_and_resolve_options() -> None:
    task = {"id": "t", "name": "Campo", "custom_fields": [
        {"name": "Cliente", "type": "short_text", "value": "Acme"},
        {"name": "Fase", "type": "drop_down", "value": 1,
         "type_config": {"options": [{"orderindex": 0, "name": "A"}, {"orderindex": 1, "name": "Proposta"}]}},
        {"name": "Tipos", "type": "labels", "value": ["x"],
         "type_config": {"options": [{"id": "x", "label": "Renovação"}]}},
        {"name": "Vazio", "type": "short_text", "value": ""},
        {"name": "Usuário", "type": "users", "value": [{"id": 1}]},
    ]}
    text = _task_text(task, "Lista", {})
    assert "Cliente: Acme" in text and "Fase: Proposta" in text and "Tipos: Renovação" in text
    assert "Vazio" not in text and "Usuário" not in text


def test_clickup_doc_text_preserves_page_hierarchy_and_treats_title_only_as_empty() -> None:
    text = _doc_text("Playbook", [{"name": "Onboarding", "content": "Passo", "pages": [
        {"name": "Acessos", "content": "ClickUp"}]}])
    assert text == "# Playbook\n\n## Onboarding\n\nPasso\n\n### Acessos\n\nClickUp"
    assert _doc_text("Vazio", [{"name": "", "content": ""}]) == ""


def test_clickup_unchanged_items_are_not_reread_but_stay_in_the_catalog() -> None:
    known = {"clickup:task:t1": (EDITED, "indexed"), "clickup:task:t2": (EDITED, "indexed"),
             "clickup:task:t3": (EDITED, "indexed"), "clickup:doc:d1": (EDITED, "indexed"),
             "clickup:doc:d2": (EDITED, "skipped")}
    client, result = discover(known_documents=known)
    assert result.documents == [] and client.page_reads == []
    assert result.full_snapshot is False and result.removed_file_ids == ()
    # An empty (skipped) Doc stays out of the library, exactly as when it was first indexed.
    assert ids(result.catalog_documents) == ["clickup:doc:d1", "clickup:task:t1", "clickup:task:t2", "clickup:task:t3"]


def test_clickup_empty_doc_is_reported_for_skipping_and_kept_out_of_the_catalog() -> None:
    class EmptyDoc(FakeClient):
        def doc_pages(self, *, credentials, workspace_id, doc_id):
            self.page_reads.append(doc_id)
            return [{"name": "", "content": ""}]

    _, result = discover(EmptyDoc())
    empty = next(item for item in result.documents if item.external_file_id == "clickup:doc:d1")
    assert empty.text == ""
    assert "clickup:doc:d1" not in ids(result.catalog_documents) and "clickup:task:t1" in ids(result.catalog_documents)


def test_clickup_naive_database_timestamps_still_match_unchanged_items() -> None:
    known = {"clickup:task:t1": (EDITED.replace(tzinfo=None), "indexed")}
    _, result = discover(known_documents=known)
    assert "clickup:task:t1" not in ids(result.documents)


def test_clickup_changed_forced_and_full_runs_reread_content() -> None:
    changed = {"clickup:task:t1": (EDITED - timedelta(days=1), "indexed")}
    _, result = discover(known_documents=changed)
    assert "clickup:task:t1" in ids(result.documents)
    same = {"clickup:task:t1": (EDITED, "indexed")}
    _, result = discover(known_documents=same, force_file_ids={"clickup:task:t1"})
    assert "clickup:task:t1" in ids(result.documents)
    _, result = discover(known_documents=same, force_full=True)
    assert "clickup:task:t1" in ids(result.documents) and result.full_snapshot is True


def test_clickup_deleted_task_is_reported_as_removed() -> None:
    known = {"clickup:task:gone": (EDITED, "indexed"), "clickup:task:t1": (EDITED, "indexed")}
    _, result = discover(known_documents=known)
    assert result.removed_file_ids == ("clickup:task:gone",)


def test_clickup_unavailable_docs_block_only_doc_removals() -> None:
    known = {"clickup:task:gone": (EDITED, "indexed"), "clickup:doc:old": (EDITED, "indexed")}
    _, result = discover(FakeClient(docs_error=SourceItemUnavailable), known_documents=known)
    assert result.removed_file_ids == ("clickup:task:gone",)  # tasks were read fine; Docs were not
    assert "clickup:task:t1" in ids(result.documents) and not any(i.startswith("clickup:doc:") for i in ids(result.documents))


class RestrictedList(FakeClient):
    def list_tasks(self, *, credentials, list_id, include_closed):
        if list_id == "A":
            raise SourceItemUnavailable("restricted_resource")
        return super().list_tasks(credentials=credentials, list_id=list_id, include_closed=include_closed)


def test_clickup_unreadable_list_is_skipped_and_blocks_only_task_removals() -> None:
    known = {"clickup:task:t1": (EDITED, "indexed"), "clickup:doc:old": (EDITED, "indexed")}
    _, result = discover(RestrictedList(), known_documents=known)
    assert "clickup:task:t3" in ids(result.documents) and "clickup:task:t1" not in ids(result.documents)
    assert result.removed_file_ids == ("clickup:doc:old",)  # the Doc is gone; the unreadable list proves nothing


@pytest.mark.parametrize("client_class", [RestrictedList, None])
def test_clickup_partial_reads_never_become_a_full_snapshot(client_class) -> None:
    """A full snapshot removes every indexed document missing from the run: forbidden after a partial read."""
    client = client_class() if client_class else FakeClient(docs_error=SourceItemUnavailable)
    known = {"clickup:task:t1": (EDITED, "indexed"), "clickup:task:t2": (EDITED, "indexed")}
    _, result = discover(client, known_documents=known, force_full=True)
    assert result.full_snapshot is False


def test_clickup_failed_doc_page_read_keeps_the_indexed_doc_and_forbids_a_full_snapshot() -> None:
    class BrokenPages(FakeClient):
        def doc_pages(self, *, credentials, workspace_id, doc_id):
            raise SourceItemUnavailable("restricted_resource")

    known = {"clickup:doc:d1": (EDITED - timedelta(days=1), "indexed")}
    _, result = discover(BrokenPages(), known_documents=known, force_full=True)
    assert "clickup:doc:d1" not in result.removed_file_ids and result.full_snapshot is False
    assert "clickup:doc:d1" in ids(result.catalog_documents) and "clickup:doc:d1" not in ids(result.documents)


@pytest.mark.parametrize("parent", [{"id": "s1", "type": "4"}, {"id": "zzz", "type": 99}, {"type": 5}, None, {"id": "gone", "type": 6}])
def test_clickup_doc_with_an_unknown_or_unresolvable_parent_falls_back_to_its_workspace(parent) -> None:
    class Odd(FakeClient):
        def workspace_docs(self, *, credentials, workspace_id):
            return [{"id": "odd", "name": "Odd", "date_updated": EDITED_MS, "parent": parent}]

    _, result = discover(Odd(), known_documents={"clickup:doc:odd": (EDITED - timedelta(days=1), "indexed")})
    doc = next(item for item in result.documents if item.external_file_id == "clickup:doc:odd")
    expected = "clickup:space:s1" if parent == {"id": "s1", "type": "4"} else "clickup:workspace:w1"
    assert doc.parent_ids == (expected,) and "clickup:doc:odd" not in result.removed_file_ids


def test_clickup_projection_exposes_only_selected_containers_and_their_ancestors() -> None:
    class TwoSpaces(FakeClient):
        def spaces(self, *, credentials, workspace_id):
            return [{"id": "s1", "name": "Projetos"}, {"id": "s2", "name": "RH confidencial"}]

        def folders(self, *, credentials, space_id):
            return super().folders(credentials=credentials, space_id=space_id) if space_id == "s1" else []

        def folderless_lists(self, *, credentials, space_id):
            return super().folderless_lists(credentials=credentials, space_id=space_id) if space_id == "s1" else [
                {"id": "C", "name": "Salários"}]

    provider = ClickUpDocumentProvider(TwoSpaces(), Cipher())
    visible = provider.folders_for_selections(
        encrypted_credentials="x", selections=[Selection("folder", "clickup:folder:f1")])
    assert [item.id for item in visible] == ["clickup:folder:f1", "clickup:list:A", "clickup:space:s1", "clickup:workspace:w1"]
    everything = provider.folders_for_selections(encrypted_credentials="x", selections=[Selection("all_accessible")])
    assert "clickup:list:C" in {item.id for item in everything}
    assert not any("RH" in item.name for item in visible)


def test_clickup_item_listed_by_two_lists_is_indexed_once() -> None:
    class Twice(FakeClient):
        def list_tasks(self, *, credentials, list_id, include_closed):
            return self.tasks["A"]

    _, result = discover(Twice())
    assert ids(result.documents).count("clickup:task:t1") == 1
    assert [item.external_file_id for item in result.catalog_documents].count("clickup:task:t1") == 1


def test_clickup_list_tasks_stops_on_an_empty_page_even_if_last_page_is_never_true(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    pages = iter([{"tasks": [{"id": "1"}], "last_page": False}, {"tasks": [], "last_page": False}])
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, json=next(pages), request=httpx.Request("GET", url)))
    assert [task["id"] for task in client.list_tasks(credentials=CREDENTIALS, list_id="L", include_closed=False)] == ["1"]


def test_clickup_429_waits_for_the_ratelimit_reset_header(monkeypatch) -> None:
    from app.integrations.http import RemoteHttp, parse_rate_limit_reset

    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    assert parse_rate_limit_reset(str(int(now.timestamp()) + 12), now=now) == 12
    assert parse_rate_limit_reset("30", now=now) is None and parse_rate_limit_reset(None, now=now) is None
    assert parse_rate_limit_reset(str(int(now.timestamp() * 1000)), now=now) is None  # milliseconds
    assert parse_rate_limit_reset(str(int(now.timestamp()) - 5), now=now) == 1.0  # reset already past (clock skew)
    waits: list[float] = []
    reset = str(int(datetime.now(UTC).timestamp()) + 20)
    replies = iter([httpx.Response(429, headers={"X-RateLimit-Reset": reset}, json={}, request=httpx.Request("GET", "https://x")),
                    httpx.Response(200, json={"teams": []}, request=httpx.Request("GET", "https://x"))])
    monkeypatch.setattr(httpx, "get", lambda url, **kw: next(replies))
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb",
                                http=RemoteHttp(sleep=waits.append, monotonic=lambda: 0.0, jitter=lambda: 1.0))
    assert client.workspaces(credentials=CREDENTIALS) == []
    assert waits and 15 <= waits[0] <= 30  # the reset (~20 s), not the 1 s exponential default


def test_clickup_token_response_without_access_token_is_an_invalid_authorization(monkeypatch) -> None:
    client = ClickUpOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(200, json={}, request=httpx.Request("POST", url)))
    with pytest.raises(ClickUpOAuthInvalid):
        client.exchange_code(code="c")


def test_clickup_account_lookup_failure_aborts_the_connection_without_creating_a_source() -> None:
    engine = _service_fixture()

    class Forbidden(ServiceClient):
        def account_email(self, *, credentials):
            raise SourceItemUnavailable("restricted_resource")

    try:
        with Session(engine) as session:
            organization, admin = _member(session, MembershipRole.ADMIN, login=True)
            service = ClickUpConnectionService(session, ServiceCipher(), Forbidden())
            raw = service.begin(scope=OrganizationScope(organization.id), user_id=admin.id,
                                session_secret="session").split("state=")[1]
            with pytest.raises(ClickUpOAuthInvalid):
                service.complete(raw_state=raw, code="code", session_secret="session")
            assert session.query(DataSource).count() == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_clickup_progress_reports_each_list_and_workspace() -> None:
    progress = []
    discover(progress_callback=lambda done, total: progress.append((done, total)))
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_clickup_revoked_token_surfaces_as_unauthorized() -> None:
    class Revoked(FakeClient):
        def workspaces(self, *, credentials):
            raise ClickUpRemoteUnauthorized()

    with pytest.raises(ClickUpRemoteUnauthorized):
        discover(Revoked())


def test_clickup_registry_adapter_is_wired_with_its_own_key_and_capabilities() -> None:
    from cryptography.fernet import Fernet

    settings = Settings(database_url=DB, clickup_oauth_client_id="cid", clickup_oauth_client_secret="sec",
                        clickup_oauth_redirect_uri="https://api.test/data-sources/clickup/oauth/callback",
                        clickup_token_encryption_key=Fernet.generate_key().decode())
    adapter = IntegrationRegistry(settings).get("clickup")
    assert adapter.key == "clickup"
    assert adapter.capabilities.supports_oauth and not adapter.capabilities.supports_incremental_sync
    assert adapter._provider.include_closed_tasks is False
    assert settings.cipher_keys("clickup") == [settings.clickup_token_encryption_key.get_secret_value()]


def test_clickup_in_production_requires_its_own_distinct_encryption_key() -> None:
    from cryptography.fernet import Fernet

    shared = Fernet.generate_key().decode()
    base = {
        "_env_file": None,
        "database_url": DB,
        "environment": "production",
        "clickup_oauth_client_id": "cid",
        "auth_proxy_secret": "test-only-proxy-secret-at-least-32-chars",
        "auth_trusted_proxy_cidrs": "127.0.0.1/32",
    }
    with pytest.raises(ValidationError, match="ClickUp requires its own encryption key"):
        Settings(**base)
    with pytest.raises(ValidationError, match="distinct encryption key"):
        Settings(**base, clickup_token_encryption_key=shared, notion_token_encryption_key=shared,
                 notion_token_encryption_legacy_fallback=False)


def _service_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


class ServiceClient:
    def authorization_url(self, *, state: str) -> str:
        return f"https://app.clickup.com/api?state={state}"

    def exchange_code(self, *, code: str) -> OAuthCredentials:
        return OAuthCredentials("clickup-token", None, None)

    def account_email(self, *, credentials: OAuthCredentials) -> str | None:
        return "owner@example.test"


class ServiceCipher:
    def encrypt(self, credentials: OAuthCredentials) -> str:
        return "clickup-ciphertext"


def _member(session: Session, role: MembershipRole, *, organization=None, login: bool = False):
    organization = organization or Organization(name="Acme")
    user = User(email=f"user-{uuid4()}@example.test")
    session.add_all([organization, user])
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=role, is_active=True))
    if login:
        session.add(UserSession(user_id=user.id, secret_hash=hash_secret("session"),
                                expires_at=datetime.now(UTC) + timedelta(hours=1)))
    session.flush()
    return organization, user


def test_clickup_connection_creates_one_encrypted_source_per_organization_and_audits_it() -> None:
    engine = _service_fixture()
    try:
        with Session(engine) as session:
            organization, admin = _member(session, MembershipRole.ADMIN, login=True)
            service = ClickUpConnectionService(session, ServiceCipher(), ServiceClient())
            scope = OrganizationScope(organization.id)
            for _ in range(2):  # reconnecting reuses the source instead of duplicating it
                url = service.begin(scope=scope, user_id=admin.id, session_secret="session")
                raw = url.split("state=")[1]
                source = service.complete(raw_state=raw, code="code", session_secret="session")
            assert (source.provider, source.status, source.account_email) == ("clickup", "connected", "owner@example.test")
            assert source.encrypted_credentials == "clickup-ciphertext"
            assert session.query(DataSource).count() == 1
            assert session.query(OAuthConnectionState).filter(OAuthConnectionState.consumed_at.is_(None)).count() == 0
            disconnected = service.disconnect(scope=scope, user_id=admin.id, source_id=source.id)
            assert (disconnected.status, disconnected.encrypted_credentials, disconnected.account_email) == (
                "disconnected", None, None)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_clickup_connection_denies_members_and_other_organizations_and_foreign_sources() -> None:
    engine = _service_fixture()
    try:
        with Session(engine) as session:
            organization, member = _member(session, MembershipRole.MEMBER)
            _, other_admin = _member(session, MembershipRole.ADMIN)
            _, admin = _member(session, MembershipRole.ADMIN, organization=organization)
            google = DataSource(organization_id=organization.id, provider="google_drive",
                                encrypted_credentials="g", status="connected", connected_by_user_id=admin.id)
            session.add(google)
            session.flush()
            service = ClickUpConnectionService(session, ServiceCipher(), ServiceClient())
            scope = OrganizationScope(organization.id)
            with pytest.raises(ClickUpAccessDenied):
                service.begin(scope=scope, user_id=member.id, session_secret="session")
            with pytest.raises(ClickUpAccessDenied):
                service.begin(scope=scope, user_id=other_admin.id, session_secret="session")
            with pytest.raises(ClickUpOAuthInvalid):  # a Google source can never be re-authorised as ClickUp
                service.begin(scope=scope, user_id=admin.id, session_secret="session", source_id=google.id)
            with pytest.raises(ClickUpAccessDenied):
                service.disconnect(scope=scope, user_id=admin.id, source_id=google.id)
            assert google.status == "connected" and google.encrypted_credentials == "g"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _sync_once(session: Session, organization, user, source, folder, client, *, known_documents=None):
    """Runs the provider output through the real reconciliation and library projection."""
    from app.ingestion.service import IngestionService

    provider = ClickUpDocumentProvider(client, Cipher())
    result = provider.discover(encrypted_credentials="x", selections=[Selection("all_accessible")],
                               known_documents=known_documents)
    containers = provider.folders_for_selections(encrypted_credentials="x", selections=[Selection("all_accessible")])
    service = IngestionService(session)
    job = service.claim(job_id=service.enqueue(scope=OrganizationScope(organization.id), user_id=user.id,
                                               workspace_folder_id=folder.id).id)
    service.apply_reconciliation(job_id=job.id, run_token=job.run_token, documents=result,
                                 manual_folders=containers)
    LibraryService(session).project_successful_sync(
        organization_id=organization.id, source=source,
        documents=result.catalog_documents if result.catalog_documents is not None else result.documents,
        folders=containers, workspace_folder_id=folder.id)
    session.flush()
    return result


def _known(session: Session, folder) -> dict:
    return {row.external_file_id: (row.modified_at, row.index_status) for row in session.scalars(
        select(Document).where(Document.workspace_folder_id == folder.id))}


def _states(session: Session, folder) -> dict[str, str]:
    return {key: value[1] for key, value in _known(session, folder).items()}


def test_clickup_sync_persists_documents_projects_the_hierarchy_and_prunes_deleted_tasks(session: Session) -> None:
    organization, user, source = seed(session)
    source.provider = "clickup"
    folder = space(session, organization, source, "all", created_at=T0)
    client = FakeClient()

    _sync_once(session, organization, user, source, folder, client)
    assert _states(session, folder) == {
        "clickup:doc:d1": "indexed", "clickup:doc:d2": "indexed", "clickup:task:t1": "indexed",
        "clickup:task:t2": "indexed", "clickup:task:t3": "indexed"}
    nodes = {node.external_id: node for node in session.scalars(select(LibraryNode))}
    by_id = {node.id: node for node in nodes.values()}

    def path(external_id: str) -> str:
        names, node = [], nodes[external_id]
        while node is not None:
            names.append(node.name)
            node = by_id.get(node.parent_id)
        return " > ".join(reversed(names))

    assert path("clickup:task:t1") == "ClickUp > Acme > Projetos > Clientes > Contratos > Contrato Acme"
    assert path("clickup:task:t2").endswith("Clientes > Contratos > Revisar minuta")
    assert path("clickup:task:t3") == "ClickUp > Acme > Projetos > Backlog > Sem descrição"  # title-only tasks stay findable
    assert path("clickup:doc:d2") == "ClickUp > Acme > Wiki geral"

    again = _sync_once(session, organization, user, source, folder, client, known_documents=_known(session, folder))
    assert again.documents == [] and again.full_snapshot is False
    assert set(_states(session, folder).values()) == {"indexed"}
    assert "clickup:task:t1" in {node.external_id for node in session.scalars(select(LibraryNode))}

    del client.tasks["A"][1]  # t2 deleted in ClickUp
    _sync_once(session, organization, user, source, folder, client, known_documents=_known(session, folder))
    assert _states(session, folder)["clickup:task:t2"] == "removed"
    assert "clickup:task:t2" not in {node.external_id for node in session.scalars(select(LibraryNode))}
    assert _states(session, folder)["clickup:task:t1"] == "indexed"
