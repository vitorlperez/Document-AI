"""Synthetic list -> count/themes -> select by topic reproduction."""
# ruff: noqa: F811
import pytest
from sqlalchemy import select

from app.knowledge.agent import AgentLimits, AgentService, ConversationService
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import AIProviderUnavailable
from app.library.models import LibraryNode
from app.library.service import SyncAccessDenied
from app.organizations.models import Membership, Organization
from app.workspaces.models import WorkspaceFolder
from tests.unit.test_agent_flow import IntentProvider, _folder_with_files, _intent
from tests.unit.test_semantic_questions import chunk
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


class CatalogAI(IntentProvider):
    def __init__(self):
        super().__init__(intent=_intent("list_files", "library"))
        self.analysis_calls = []
        self.analysis_error = False
        self.invalid_quote = False

    def embed(self, *, texts):
        self.embed_calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    def analyze_file_topics(self, *, question, files, model):
        self.analysis_calls.append(files)
        if self.analysis_error:
            raise AIProviderUnavailable("synthetic timeout")
        result = {}
        for index, item in enumerate(files, 1):
            text = next((text for text in item["chunks"] if "Software Engineer" in text), item["chunks"][0])
            if not text:
                continue
            career = "Software Engineer" in text
            result[index] = {
                "matches": career,
                "topic": "Carreira profissional" if career else "Planejamento",
                "evidence": "invented unsupported quote" if self.invalid_quote else text,
            }
        return result


def setup(session):
    scope, user, folder, document = _folder_with_files(session)
    workspace = session.get(WorkspaceFolder, document.workspace_folder_id)
    organization = session.get(Organization, workspace.organization_id)
    career = chunk(session, organization, workspace, name="Profile.pdf",
                   text="Software Engineer com experiência em Python.")
    doc = session.get(Document, career.document_id)
    node = LibraryNode(organization_id=scope.organization_id, source_id=workspace.source_id,
                       parent_id=folder.id, external_id=doc.external_file_id,
                       kind="file", name="Profile.pdf")
    session.add(node)
    session.commit()
    provider = CatalogAI()
    conv, _ = ConversationService(session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question="Quais arquivos tenho no Drive?",
    )
    return scope, user, folder, node, provider, conv


def turn(session, case, question, intent, *, target="previous_answer_files", mentions=()):
    scope, user, _folder, _node, provider, conv = case
    service = ConversationService(session)
    _, history = service.history(scope=scope, user_id=user.id, conversation_id=conv.id)
    provider.intent = _intent(intent, target)
    result, tools, refs = AgentService(session, provider, AgentLimits()).ask(
        scope=scope, user_id=user.id, question=question, providers=["google_drive"],
        mentions=list(mentions), history=history,
    )
    service.append(conversation=conv, role="user", content=question,
                   context={"mentions": [{"kind": k, "node_id": str(v)} for k, v in mentions]})
    service.append(conversation=conv, role="assistant", content=result.answer,
                   context={"references": refs, "resolved_context": result.resolved_context}, response={
                       "citations": [{"document_id": str(c.document_id)} for c in result.citations],
                   })
    session.commit()
    return result, tools, refs


def test_pasted_multiturn_flow_counts_catalog_and_selects_only_matching_files(semantic_session):
    case = setup(semantic_session)
    listed, _, refs = turn(semantic_session, case, "Quais arquivos tenho no Drive?", "list_files", target="library")
    assert len(refs) == 3
    assert "3 arquivos" in listed.answer
    counted, _, refs = turn(semantic_session, case, "Quantos sao e quais os principais temas?", "inventory_stats")
    assert "3 arquivos" in counted.answer
    assert "2 com conteúdo indexado" in counted.answer
    assert "Carreira profissional" in counted.answer, case[4].analysis_calls
    assert len(refs) == 3
    selected, _, refs = turn(semantic_session, case, "Quais falam sobre currículo e carreira profissional?", "select_files_by_topic")
    assert [r["name"] for r in refs] == ["Profile.pdf"]
    assert [c.document_name for c in selected.citations] == ["Profile.pdf"]
    assert "Indexed.pdf" not in selected.answer
    assert "1 de 3" in selected.answer
    assert not case[4].embed_calls


@pytest.mark.parametrize("intent", ["inventory_stats", "select_files_by_topic"])
def test_followups_revalidate_removed_files_without_widening(semantic_session, intent):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", target="library")
    semantic_session.delete(case[3])
    semantic_session.commit()
    with pytest.raises((SyncAccessDenied, ValueError)):
        turn(semantic_session, case, "Quantos ou quais?", intent)
    assert not case[4].analysis_calls


def test_current_selection_overrides_history(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", target="library")
    result, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", mentions=[("file", case[3].id)])
    assert "1 arquivo" in result.answer
    assert len(refs) == 1


def test_stats_after_folder_listing_counts_unindexed(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", mentions=[("folder", case[2].id)])
    counted, _, refs = turn(semantic_session, case, "Quantos são e quais os temas?", "inventory_stats")
    assert "São 3 arquivos" in counted.answer
    assert "2 com conteúdo indexado" in counted.answer
    assert len(refs) == 3


def test_topic_selection_after_folder_listing_skips_unrelated(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", mentions=[("folder", case[2].id)])
    selected, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")
    assert [r["name"] for r in refs] == ["Profile.pdf"]
    assert [c.document_name for c in selected.citations] == ["Profile.pdf"]


@pytest.mark.parametrize("mode", ["timeout", "invalid_quote"])
def test_topic_failure_is_unknown_never_unfiltered_dump(semantic_session, mode):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", target="library")
    case[4].analysis_error = mode == "timeout"
    case[4].invalid_quote = mode == "invalid_quote"
    result, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")
    assert not refs
    assert "Não foi possível avaliar" in result.answer
    assert not result.citations
    assert "invented" not in result.answer


def test_membership_revoked_blocks_stats(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", target="library")
    member = semantic_session.scalar(select(Membership).where(Membership.user_id == case[1].id))
    member.is_active = False
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied):
        turn(semantic_session, case, "Quantos?", "inventory_stats")


def add_file(session, case, name, text, *, workspace=None):
    scope, _user, folder, _node, _provider, _conv = case
    doc = session.scalar(select(Document).where(Document.organization_id == scope.organization_id))
    workspace = workspace or session.get(WorkspaceFolder, doc.workspace_folder_id)
    organization = session.get(Organization, workspace.organization_id)
    indexed = chunk(session, organization, workspace, name=name, text=text)
    doc = session.get(Document, indexed.document_id)
    node = LibraryNode(organization_id=organization.id, source_id=workspace.source_id,
                       parent_id=folder.id, external_id=doc.external_file_id, kind="file", name=name)
    session.add(node)
    session.commit()
    return node, doc


def test_same_names_remain_distinct_and_match_beyond_first_24_sources(semantic_session):
    case = setup(semantic_session)
    for _ in range(25):
        add_file(semantic_session, case, "Documento sem título", "O plano prioriza clientes existentes.")
    listed, _, refs = turn(semantic_session, case, "Liste", "list_files", target="library")
    assert len(refs) == len({r["id"] for r in refs}) == 28
    assert listed.answer.count("Documento sem título") == 25
    selected, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")
    assert [r["name"] for r in refs] == ["Profile.pdf"]
    assert "1 de 28" in selected.answer
    assert [len(batch) for batch in case[4].analysis_calls] == [10, 10, 7]


def test_partial_inventory_never_becomes_full_drive_count(semantic_session, monkeypatch):
    from app.knowledge import agent

    case = setup(semantic_session)
    monkeypatch.setattr(agent, "INVENTORY_MAX_ITEMS", 2)
    listed, _, refs = turn(semantic_session, case, "Liste", "list_files", target="library")
    assert len(refs) == 2
    assert "primeiros 2 de 3" in listed.answer
    counted, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats")
    assert len(refs) == 2
    assert "São 2 arquivos" in counted.answer
    assert "listagem consultada é parcial" in counted.answer
    assert counted.resolved_context["inventory_truncated"] is True
    selected, _, _ = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")
    assert "origem é parcial" in selected.answer


def test_same_source_denied_folder_is_not_counted_or_sent_to_ai(semantic_session):
    case = setup(semantic_session)
    current = semantic_session.scalar(select(WorkspaceFolder))
    denied = WorkspaceFolder(organization_id=current.organization_id, source_id=current.source_id,
                             external_folder_id="denied", name="Denied", status="disconnected",
                             uniform_access_confirmed=True)
    semantic_session.add(denied)
    semantic_session.commit()
    add_file(semantic_session, case, "SECRET.pdf", "Software Engineer SECRET-DENIED", workspace=denied)
    result, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", target="library")
    assert len(refs) == 3
    assert "SECRET" not in repr(case[4].analysis_calls) + result.answer + repr(result.citations)


def test_other_tenant_reference_is_rejected(semantic_session):
    from tests.unit.test_semantic_questions import context

    case = setup(semantic_session)
    other_org, _other_user, workspace = context(semantic_session)
    root = LibraryNode(organization_id=other_org.id, source_id=workspace.source_id,
                       external_id="foreign-root", kind="source", name="Foreign")
    semantic_session.add(root)
    semantic_session.flush()
    node = LibraryNode(organization_id=other_org.id, source_id=workspace.source_id,
                       parent_id=root.id, external_id="foreign-file", kind="file", name="SECRET.pdf")
    semantic_session.add(node)
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied):
        turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic", mentions=[("file", node.id)])
    assert not case[4].analysis_calls


def test_folder_provenance_survives_statistics_and_rejects_moved_file(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", mentions=[("folder", case[2].id)])
    _counted, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats")
    assert all(r["folder_id"] == str(case[2].id) for r in refs)
    case[3].parent_id = case[2].parent_id
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied):
        turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")


def test_deindexing_changes_content_coverage_but_keeps_file_count(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", target="library")
    doc = semantic_session.scalar(select(Document).where(Document.name == "Profile.pdf"))
    doc.index_status = "failed"
    semantic_session.commit()
    counted, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats")
    assert "São 3 arquivos" in counted.answer and len(refs) == 3
    assert "1 com conteúdo indexado" in counted.answer
    assert "Profile.pdf" not in repr(case[4].analysis_calls)


def test_matching_evidence_in_later_snapshot_chunk_keeps_grounding(semantic_session):
    case = setup(semantic_session)
    doc = semantic_session.scalar(select(Document).where(Document.name == "Profile.pdf"))
    first = semantic_session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    first.text = "Introdução ao documento."
    semantic_session.add(DocumentChunk(organization_id=doc.organization_id,
                                      workspace_folder_id=doc.workspace_folder_id,
                                      document_id=doc.id, position=1,
                                      text="Software Engineer com experiência em Python.",
                                      search_text="Software Engineer com experiência em Python."))
    semantic_session.commit()
    selected, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic", target="library")
    assert [r["name"] for r in refs] == ["Profile.pdf"]
    assert selected.citations[0].excerpt == "Software Engineer com experiência em Python."


def test_topic_adapter_uses_closed_schema_and_drops_out_of_range_files(monkeypatch):
    import json

    from app.knowledge.questions import OpenAIQuestionProvider

    provider = OpenAIQuestionProvider("fake")
    sent = []

    def post(path, body):
        sent.append(body)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
            "files": [
                {"file": 1, "matches": True, "topic": "Carreira", "evidence": "Software Engineer"},
                {"file": 99, "matches": True, "topic": "Foreign", "evidence": "secret"},
            ],
        })}]}]}

    monkeypatch.setattr(provider, "_post", post)
    result = provider.analyze_file_topics(question="Quais falam de carreira?",
                                         files=[{"name": "Profile.pdf", "chunks": ["Software Engineer"]}])
    assert set(result) == {1}
    assert sent[0]["store"] is False
    assert sent[0]["text"]["format"]["strict"] is True
    assert "untrusted data" in sent[0]["instructions"]


def test_byte_limit_is_explicit_partial_list_with_exact_catalog_total(semantic_session):
    from app.knowledge.agent import AgentLimits

    case = setup(semantic_session)
    result, _, refs = AgentService(semantic_session, case[4], AgentLimits(max_result_bytes=400)).ask(
        scope=case[0], user_id=case[1].id, question="Liste", providers=["google_drive"], mentions=[], history=[],
    )
    assert len(refs) < 3
    assert "3 arquivos" in result.answer
    assert result.resolved_context["inventory_truncated"] is True
    assert result.resolved_context["inventory_returned"] == len(refs)


def test_title_only_file_remains_counted_but_has_unknown_topic(semantic_session):
    case = setup(semantic_session)
    add_file(semantic_session, case, 'Currículo.pdf', 'Currículo')
    result, _, refs = turn(semantic_session, case, 'Quantos e quais temas?', 'inventory_stats', target='library')
    assert len(refs) == 4
    assert 'São 4 arquivos' in result.answer
    assert 'temas de 2 arquivo(s)' in result.answer
    assert 'Currículo.pdf' not in repr(case[4].analysis_calls)


def test_empty_topic_selection_stays_empty_on_next_count(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, 'Liste', 'list_files', target='library')
    doc = semantic_session.scalar(select(Document).where(Document.name == 'Profile.pdf'))
    first = semantic_session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    first.text = 'O plano prioriza clientes existentes.'
    semantic_session.commit()
    selected, _, refs = turn(semantic_session, case, 'Quais falam de carreira?', 'select_files_by_topic')
    assert refs == [] and 'Encontrei 0' in selected.answer
    counted, _, refs = turn(semantic_session, case, 'Quantos são?', 'inventory_stats')
    assert refs == [] and 'São 0 arquivos' in counted.answer
    assert case[4].intent_calls[-1]['context']['previous_selection_empty'] is True
