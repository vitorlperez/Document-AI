"""Contextual fact questions: structured rewrite, inherited sources and cited abstention."""
import pytest

from app.core.scoping import OrganizationScope
from app.knowledge.agent import AgentLimits, AgentService
from app.knowledge.intent import InvalidIntent, parse_intent
from app.knowledge.models import ConversationMessage, Document
from app.library.models import LibraryNode
from tests.unit.test_document_agent import Classifies
from tests.unit.test_profile_retrieval import profile  # noqa: F401
from tests.unit.test_semantic_questions import chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

FIRST = 'Em quais empresas o Vitor trabalhou e quando?'
FOLLOWUP = 'Qual foi o último emprego?'
STANDALONE = 'Qual foi o emprego mais recente do Vitor Perez, incluindo empresa, cargo e período?'


def cited_history(document_id):
    return [
        ConversationMessage(role='user', content=FIRST, context={'mentions': []}),
        ConversationMessage(role='assistant', content=('Contexto anterior. ' * 40) +
            'Allstacks — Software Engineer — June 2025 - Present (8 months).',
            response={'citations': [{'document_id': str(document_id)}]}),
    ]


def file_node(session, workspace, document):
    root = LibraryNode(organization_id=document.organization_id, source_id=workspace.source_id,
        parent_id=None, external_id='source-root', kind='source', name='Google Drive')
    session.add(root)
    session.flush()
    node = LibraryNode(organization_id=document.organization_id, source_id=workspace.source_id,
        parent_id=root.id, external_id=document.external_file_id, kind='file', name=document.name)
    session.add(node)
    session.commit()
    return node


def test_elliptic_followup_reads_rewritten_query_and_inherited_full_resume(profile):  # noqa: F811
    session, org, user, folder, chunks = profile
    document = session.get(Document, chunks[0].document_id)
    node = file_node(session, folder, document)
    for item in chunks:
        item.embedding = [0, 1]  # Low scores must not block the inherited source.
    session.commit()
    history = cited_history(document.id)
    provider = Classifies(intent='ask_content', target='previous_answer_files', tool='retrieve_evidence',
        extra={'standalone_query': STANDALONE}, vectors={FOLLOWUP: [0, 1], STANDALONE: [1, 0]},
        answer='O emprego mais recente do Vitor é Allstacks, Software Engineer, June 2025 - Present [1].')
    result, _, _ = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(org.id), user_id=user.id, question=FOLLOWUP,
        providers=['google_drive'], mentions=[], history=history)
    assert provider.embed_calls == [[STANDALONE]]
    assert provider.last_history[-1]['content'] == history[-1].content
    assert provider.last_context['previous_answer_listed_files'] == ['Profile.pdf']
    assert result.resolved_context['mention_node_ids'] == [str(node.id)]
    assert result.resolved_context['standalone_query'] == STANDALONE
    question, evidence = provider.answer_calls[0]
    assert question == STANDALONE
    assert all(item.text in evidence[0].excerpt for item in chunks)
    assert evidence[0].chunk_ids == tuple(item.id for item in chunks)
    assert 'Allstacks' in result.answer and '(fonte 1)' in result.answer
    assert [(e.document_id, e.source_url) for e in result.citations] == [(document.id, document.source_url)]


def test_content_llm_decides_on_low_score_evidence_and_abstention_keeps_consulted_sources(semantic_session):  # noqa: F811
    session = semantic_session
    org, user, folder = context(session)
    item = chunk(session, org, folder, name='Unrelated.pdf', text='O plano prevê investimento.', embedding=[0, 1])
    question = 'Qual foi o último emprego?'
    provider = Classifies(intent='ask_content', target='library', tool='retrieve_evidence',
        extra={'standalone_query': question}, vectors={question: [1, 0]},
        answer='Insufficient evidence.', citations=[])
    result, _, _ = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(org.id), user_id=user.id, question=question,
        providers=['google_drive'], mentions=[], history=[])
    assert len(provider.answer_calls) == 1
    assert provider.answer_calls[0][1][0].score < 0.45
    assert result.confidence == 'insufficient_evidence'
    assert 'Arquivos consultados' in result.answer and 'Unrelated.pdf (fonte 1)' in result.answer
    assert result.citations[0].document_id == item.document_id
    assert result.citations[0].source_url


def test_current_file_still_overrides_cited_history_with_autonomous_query(profile):  # noqa: F811
    session, org, user, folder, chunks = profile
    old = session.get(Document, chunks[0].document_id)
    file_node(session, folder, old)
    selected_chunk = chunk(session, org, folder, name='Proposal.pdf', text='O prazo é dezembro de 2026.')
    selected_document = session.get(Document, selected_chunk.document_id)
    root = session.query(LibraryNode).filter_by(kind='source').one()
    selected_node = LibraryNode(organization_id=org.id, source_id=folder.source_id,
        parent_id=root.id, external_id=selected_document.external_file_id, kind='file', name='Proposal.pdf')
    session.add(selected_node)
    session.commit()
    rewritten = 'Qual é o prazo da proposta selecionada?'
    provider = Classifies(intent='ask_content', target='previous_answer_files', tool='retrieve_evidence',
        extra={'standalone_query': rewritten}, vectors={rewritten: [1, 0]},
        answer='O prazo é dezembro de 2026 [1].')
    result, _, _ = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(org.id), user_id=user.id, question='E o prazo?',
        providers=['google_drive'], mentions=[('file', selected_node.id)], history=cited_history(old.id))
    assert result.resolved_context['target'] == 'mentioned'
    assert provider.embed_calls == [[rewritten]]
    assert {e.document_id for e in provider.answer_calls[0][1]} == {selected_document.id}
    assert {e.document_id for e in result.citations} == {selected_document.id}


@pytest.mark.parametrize('raw', [None, 2, [], 'x' * 1001])
def test_invalid_autonomous_query_is_rejected(raw):
    with pytest.raises(InvalidIntent):
        parse_intent({'intent': 'ask_content', 'target': 'library', 'tool': 'retrieve_evidence',
                      'query': '', 'ordinals': [], 'standalone_query': raw}, listed_files=0)


def test_no_indexed_evidence_still_returns_useful_honest_answer(semantic_session):  # noqa: F811
    org, user, _ = context(semantic_session)
    provider = Classifies(intent='ask_content', target='library', tool='retrieve_evidence')
    result, _, _ = AgentService(semantic_session, provider, AgentLimits()).ask(
        scope=OrganizationScope(org.id), user_id=user.id, question=FOLLOWUP,
        providers=['google_drive'], mentions=[], history=[])
    assert provider.answer_calls == []
    assert result.confidence == 'insufficient_evidence'
    assert 'conteúdo indexado' in result.answer
    assert result.citations == []
