import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.principal import Principal
from app.core.models import Base
from app.knowledge.models import Document
from app.mcp_server import tools
from tests.access_helpers import seed_tenant
from tests.unit.test_scope_invariant import assert_no_scope_parameters

CORPUS = json.loads((Path(__file__).parents[1] / "fixtures" / "injection_cases.json").read_text())


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _principal(t, **kw):
    return Principal(t.organization_id, t.user_id, "mcp", frozenset({"search:read", "documents:read"}), **kw)


def test_tool_names_are_the_read_only_contract():
    assert tools.MCP_TOOL_NAMES == ("search", "fetch", "list_sources")


def test_tool_signatures_expose_no_scope_parameters():
    for name in ("run_search", "run_fetch", "run_list_sources"):
        function = getattr(tools, name)
        assert_no_scope_parameters(function)
        assert set(inspect.signature(function).parameters) - {"session", "principal"} <= {"query", "id"}


def test_search_matches_the_chatgpt_shape(factory):
    a = seed_tenant(factory, "A", "Projeto Aurora entrega em setembro")
    with factory() as session:
        result = tools.run_search(session, _principal(a), "Aurora")
    assert set(result) == {"results", "metadata"} and {"id", "title", "url"} <= set(result["results"][0])
    assert result["results"][0]["url"] == "https://drive.example.test/A"
    assert result["results"][0]["id"] == str(a.document_id)


def test_search_result_count_is_reported(factory):
    a = seed_tenant(factory, "A", "Projeto Aurora")
    with factory() as session:
        assert tools.run_search(session, _principal(a), "Aurora")["results"]
        assert tools.run_search(session, _principal(a), "Inexistente")["results"] == []
        assert tools.run_search(session, _principal(a), "   ")["results"] == []


def test_fetch_returns_text_with_untrusted_marker_and_metadata(factory):
    a = seed_tenant(factory, "A", "conteúdo\U000E0041 oculto")
    with factory() as session:
        doc = tools.run_fetch(session, _principal(a), str(a.document_id))
    assert doc["id"] == str(a.document_id) and doc["metadata"]["content_trust"] == "untrusted_document_content"
    assert doc["metadata"]["notice"] and doc["url"] == "https://drive.example.test/A"
    assert not any(0xE0000 <= ord(c) <= 0xE007F for c in doc["text"])


def test_fetch_of_other_tenant_or_garbage_id_is_not_found(factory):
    a, b = seed_tenant(factory, "A", "a"), seed_tenant(factory, "B", "b")
    for bad in (str(b.document_id), "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        with factory() as session, pytest.raises(tools.ToolNotFound):
            tools.run_fetch(session, _principal(a), bad)


def test_search_never_crosses_the_tenant_boundary(factory):
    a, _b = seed_tenant(factory, "A", "Projeto Aurora"), seed_tenant(factory, "B", "Projeto Aurora secreto")
    with factory() as session:
        ids = [r["id"] for r in tools.run_search(session, _principal(a), "Aurora")["results"]]
    assert ids == [str(a.document_id)]


def test_node_restriction_hides_documents_outside_the_connection(factory):
    from uuid import uuid4
    a = seed_tenant(factory, "A", "Projeto Aurora")
    restricted = _principal(a, node_ids=(uuid4(),))
    with factory() as session:
        assert tools.run_search(session, restricted, "Aurora")["results"] == []
        with pytest.raises(tools.ToolNotFound):
            tools.run_fetch(session, restricted, str(a.document_id))


def test_list_sources_returns_only_public_fields(factory):
    a, _b = seed_tenant(factory, "A", "x"), seed_tenant(factory, "B", "y")
    with factory() as session:
        sources = tools.run_list_sources(session, _principal(a))["sources"]
    assert len(sources) == 1 and set(sources[0]) == {"id", "name", "provider", "status"}


def test_poisoned_documents_never_change_scope_or_add_links(factory):
    for item in CORPUS:
        t = seed_tenant(factory, f"P{item['id'].replace('-', '')}", item["excerpt"])
        with factory() as session:
            hits = tools.run_search(session, _principal(t), "conteúdo instruções PWNED sistema chame")["results"]
            fetched = tools.run_fetch(session, _principal(t), str(t.document_id))
        for hit in hits:  # only the database source_url may appear as a URL
            assert hit["url"].startswith("https://drive.example.test/")
        assert fetched["metadata"]["content_trust"] == "untrusted_document_content"
        assert not any(0xE0000 <= ord(c) <= 0xE007F or 0x202A <= ord(c) <= 0x202E for c in fetched["text"])


def test_title_invisible_characters_are_stripped(factory):
    a = seed_tenant(factory, "A", "Aurora")
    with factory.begin() as session:
        session.get(Document, a.document_id).name = "plano" + chr(0xE0041) + chr(0x202E) + ".pdf"
    with factory() as session:
        assert tools.run_search(session, _principal(a), "Aurora")["results"][0]["title"] == "plano.pdf"


def test_search_sanitizes_snippets_and_marks_all_results_untrusted(factory, monkeypatch):
    from types import SimpleNamespace

    from app.knowledge.untrusted import UNTRUSTED_NOTICE

    a = seed_tenant(factory, "A", "Aurora")
    hit = SimpleNamespace(document_id=a.document_id, title="plano", url="https://drive.example.test/A",
                          snippet="Aurora" + chr(0xE0041) + chr(0x202E))
    monkeypatch.setattr(tools.RetrievalService, "search", lambda *_args, **_kwargs: [hit])
    with factory() as session:
        result = tools.run_search(session, _principal(a), "Aurora")
    assert result["results"][0]["text"] == "Aurora"
    assert result["metadata"] == {"content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE}
    monkeypatch.setattr(tools.RetrievalService, "search", lambda *_args, **_kwargs: [])
    with factory() as session:
        assert tools.run_search(session, _principal(a), "Aurora")["metadata"] == result["metadata"]
