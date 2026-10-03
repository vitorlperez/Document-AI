"""Acceptance REDs for Arquivio review: real services, synthetic SQLite, fake AI.

No sanitization/resolution algorithm is replicated here. Assertions observe the
provider boundary, service result and persisted conversation. See the dossier
for approved policy versus existing coverage/authorization requirements.
"""

# Pytest intentionally injects the imported fixture under the same parameter name.
# This is the existing suite's fixture-reuse convention, not a duplicate function.
# ruff: noqa: F811

import json
import re
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.integrations.google_drive import GoogleAccessDenied
from app.integrations.models import DataSource
from app.knowledge.agent import AgentLimits, AgentService, ConversationService
from app.knowledge.models import Document
from app.knowledge.questions import GeneratedAnswer
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.organizations.models import Membership
from tests.unit.test_document_agent import Classifies
from tests.unit.test_semantic_questions import chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTION = "Reorganize a resposta anterior em tópicos."
ALPHA = "ALPHA-CURRENT: lançamento em setembro."
BETA = "BETA-SYNTHETIC-DENIED: orçamento fictício 9M."
OLD_SAFE = "OLD-WHOLE-ANSWER: interpretação anterior de alpha."
PREVIOUS = f"{OLD_SAFE} [1]. {BETA} [2]."
DENIALS = (SyncAccessDenied, GoogleAccessDenied)


@pytest.fixture(autouse=True)
def no_external_ai(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Harness violation: external HTTP attempted; only fake AI is permitted")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


class RecordingAI(Classifies):
    """Fixed intent and vectors; deliberately echoes memory to expose unsafe input.

    The fake does not authorize, filter history or choose catalog targets. With
    no previous_answer it quotes the evidence supplied by the real service.
    """

    def __init__(self):
        super().__init__(intent="restructure_previous", target="previous_answer_files",
                         tool="retrieve_evidence")
        self.classifier_inputs = []
        self.synthesis_inputs = []

    def embed(self, *, texts):
        self.embed_calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    def classify_intent(self, **kwargs):
        self.classifier_inputs.append(kwargs)
        return super().classify_intent(**kwargs)

    def synthesize_answer(self, **kwargs):
        self.synthesis_inputs.append(kwargs)
        sources = kwargs["sources"]
        text = kwargs.get("previous_answer") or (sources[0].excerpt if sources else "")
        return GeneratedAnswer(text, [1] if sources else [])


@dataclass
class Case:
    session: object
    org: object
    user: object
    workspace: object
    folder: object
    nodes: list
    docs: list
    scope: OrganizationScope
    conversation: object
    history: list
    mentions: list
    providers: list
    allowed_ids: set


def make_case(session, *, listing=False, answer_override=None):
    org, user, workspace = context(session)
    root = LibraryNode(organization_id=org.id, source_id=workspace.source_id,
                       external_id="review-root", kind="source", name="Drive sintético")
    session.add(root)
    session.flush()
    folder = LibraryNode(organization_id=org.id, source_id=workspace.source_id,
                         parent_id=root.id, external_id=workspace.external_folder_id,
                         kind="folder", name="Pasta sintética")
    session.add(folder)
    session.flush()
    nodes, docs = [], []
    for name, text in (("alpha-review.pdf", ALPHA), ("beta-denied-review.pdf", BETA)):
        item = chunk(session, org, workspace, name=name, text=text)
        doc = session.get(Document, item.document_id)
        node = LibraryNode(organization_id=org.id, source_id=workspace.source_id,
                           parent_id=folder.id, external_id=doc.external_file_id,
                           kind="file", name=name)
        session.add(node)
        nodes.append(node)
        docs.append(doc)
    session.commit()
    scope = OrganizationScope(org.id)
    conversations = ConversationService(session)
    conversation, _ = conversations.create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question="Pergunta sintética inicial",
    )
    if listing:
        result, _, refs = AgentService(
            session, Classifies(intent="list_files", tool="list_folder_inventory"), AgentLimits(),
        ).ask(scope=scope, user_id=user.id, question="Liste os arquivos", providers=["google_drive"],
              mentions=[("folder", folder.id)], history=[])
        previous = result.answer
        citations = result.citations
    else:
        previous, refs, citations = PREVIOUS, [], docs
    if answer_override is not None:
        previous = answer_override
    conversations.append(conversation=conversation, role="user", content="Pergunta sintética inicial",
                         context={"mentions": [], "providers": ["google_drive"]})
    conversations.append(
        conversation=conversation, role="assistant", content=previous,
        context={"references": refs},
        response={"citations": [{"document_id": str(c.document_id if listing else c.id)}
                                for c in citations]},
    )
    session.commit()
    _, history = conversations.history(scope=scope, user_id=user.id, conversation_id=conversation.id)
    return Case(session, org, user, workspace, folder, nodes, docs, scope, conversation, history,
                [], ["google_drive"], {doc.id for doc in docs})


def revoke(case, mode):
    if mode in {"node_removed_partial", "node_removed_total"}:
        for index in ([1] if mode.endswith("partial") else [0, 1]):
            case.session.delete(case.nodes[index])
            case.allowed_ids.discard(case.docs[index].id)
    elif mode == "document_deindexed":
        case.docs[1].index_status = "deleted"
        case.allowed_ids.discard(case.docs[1].id)
    elif mode == "scope_restricted":
        case.mentions = [("file", case.nodes[0].id)]
        case.allowed_ids = {case.docs[0].id}
    elif mode == "folder_denied":
        case.workspace.status = "disconnected"  # Folder admission, not source disconnection.
        case.allowed_ids.clear()
    elif mode == "provider_excluded":
        case.providers = ["onedrive"]
        case.allowed_ids.clear()
    elif mode == "membership_inactive":
        member = case.session.scalar(select(Membership).where(
            Membership.organization_id == case.org.id, Membership.user_id == case.user.id,
        ))
        member.is_active = False
        case.allowed_ids.clear()
    else:
        raise AssertionError(f"Unknown fixture mode: {mode}")
    case.session.commit()


def follow(case, provider):
    assert case.conversation.user_id == case.user.id
    assert case.conversation.organization_id == case.scope.organization_id == case.org.id
    return AgentService(case.session, provider, AgentLimits()).ask(
        scope=case.scope, user_id=case.user.id, question=QUESTION,
        providers=case.providers, mentions=case.mentions, history=case.history,
    )[0]


def persisted_snapshot(case):
    return [(m.id, m.role, m.content, m.context, m.response) for m in case.history]


REVOKED = ["node_removed_partial", "node_removed_total", "document_deindexed", "scope_restricted",
           "folder_denied", "provider_excluded", "membership_inactive"]
ANSWERABLE = REVOKED[:4]


def make_policy_case(session, mode):
    # Deindexing is exercised through the real persisted inventory path, which
    # already drops unreadable targets. It must also stop using old derived text.
    return make_case(session, listing=mode == "document_deindexed", answer_override=PREVIOUS)


@pytest.mark.parametrize("mode", REVOKED)
def test_policy_classifier_never_receives_entire_contaminated_answer(semantic_session, mode):
    case = make_policy_case(semantic_session, mode)
    revoke(case, mode)
    provider = RecordingAI()
    try:
        follow(case, provider)
    except DENIALS:
        assert mode in {"folder_denied", "provider_excluded", "membership_inactive"}
    except ValueError as error:
        assert mode in {"folder_denied", "provider_excluded"}
        assert str(error) == "mention is unavailable"
    payload = json.dumps(provider.classifier_inputs, ensure_ascii=False)
    # Even the portion derived from a still-authorized source must disappear:
    # the approved policy excludes the WHOLE previous answer, not substrings.
    assert OLD_SAFE not in payload, "POLICY F-A: entire previous answer reached classifier"
    assert BETA not in payload, "POLICY F-A: denied-source text reached classifier"


@pytest.mark.parametrize("mode", ANSWERABLE)
def test_policy_synthesis_never_receives_contaminated_previous_answer(semantic_session, mode):
    case = make_policy_case(semantic_session, mode)
    revoke(case, mode)
    provider = RecordingAI()
    follow(case, provider)
    for payload in provider.synthesis_inputs:
        assert OLD_SAFE not in payload.get("previous_answer", ""), "POLICY F-A: entire previous_answer retained"
        assert BETA not in payload.get("previous_answer", ""), "POLICY F-A: denied text in previous_answer"
        assert {source.document_id for source in payload["sources"]} <= case.allowed_ids
        assert all(BETA not in source.excerpt for source in payload["sources"])
        assert "beta-denied-review.pdf" not in json.dumps(payload["catalog"])


@pytest.mark.parametrize("mode", ANSWERABLE)
def test_current_citations_and_all_model_evidence_stay_authorized(semantic_session, mode):
    case = make_policy_case(semantic_session, mode)
    revoke(case, mode)
    provider = RecordingAI()
    result = follow(case, provider)
    for _question, evidence in provider.answer_calls:
        assert {source.document_id for source in evidence} <= case.allowed_ids, "F-A: residual index sent to answer model"
    for payload in provider.synthesis_inputs:
        assert {source.document_id for source in payload["sources"]} <= case.allowed_ids
    assert {citation.document_id for citation in result.citations} <= case.allowed_ids
    if mode != "node_removed_total":
        assert {citation.document_name for citation in result.citations} == {"alpha-review.pdf"}


@pytest.mark.parametrize("mode", ANSWERABLE)
def test_policy_answer_rebuilt_from_current_sources_or_honest_insufficiency(semantic_session, mode):
    case = make_policy_case(semantic_session, mode)
    revoke(case, mode)
    provider = RecordingAI()
    result = follow(case, provider)
    assert OLD_SAFE not in (result.answer or ""), "POLICY F-A: old interpretation recirculated"
    assert BETA not in (result.answer or ""), "POLICY F-A: revoked content in observable answer"
    assert {citation.document_id for citation in result.citations} <= case.allowed_ids
    assert all(BETA not in citation.excerpt for citation in result.citations)
    if case.allowed_ids:
        assert result.confidence == "supported"
        assert result.citations and ALPHA in result.answer
        assert {c.document_name for c in result.citations} == {"alpha-review.pdf"}
        assert all(c.source_url == "https://drive.example.test/alpha-review.pdf" for c in result.citations)
        assert "fonte 1" in result.answer
    else:
        assert result.confidence == "insufficient_evidence"
        assert result.citations == []
        assert result.retrieval_status == "no_indexed_content"
        assert re.search(r"evidência|indexad", result.answer or "", re.IGNORECASE)


@pytest.mark.parametrize("mode", ["node_removed_partial", "node_removed_total", "document_deindexed"])
def test_history_is_preserved_after_context_exclusion(semantic_session, mode):
    case = make_policy_case(semantic_session, mode)
    before = persisted_snapshot(case)
    revoke(case, mode)
    follow(case, RecordingAI())
    semantic_session.expire_all()
    _, fresh = ConversationService(semantic_session).history(
        scope=case.scope, user_id=case.user.id, conversation_id=case.conversation.id,
    )
    assert [(m.id, m.role, m.content, m.context, m.response) for m in fresh] == before
    assert fresh[-1].content == PREVIOUS


@pytest.mark.parametrize("source_status", ["connected", "disconnected", "reauth_required"])
def test_authorized_continuity_and_adr0007_retained_index(semantic_session, source_status):
    case = make_case(semantic_session)
    source = semantic_session.get(DataSource, case.workspace.source_id)
    source.status = source_status
    semantic_session.commit()
    provider = RecordingAI()
    result = follow(case, provider)
    assert PREVIOUS in [m["content"] for call in provider.classifier_inputs for m in call["history"]]
    assert provider.synthesis_inputs[-1]["previous_answer"] == PREVIOUS
    assert BETA in result.answer and result.confidence == "supported"
    assert {s.document_id for s in provider.synthesis_inputs[-1]["sources"]} == case.allowed_ids
    assert {c.document_id for c in result.citations} <= case.allowed_ids


def test_cross_org_mention_denied_without_content(semantic_session):
    case = make_case(semantic_session)
    foreign = make_case(semantic_session)
    mention = ("file", foreign.nodes[1].id)
    provider = RecordingAI()
    with pytest.raises((ValueError, *DENIALS)):
        AgentService(semantic_session, provider, AgentLimits()).ask(
            scope=case.scope, user_id=case.user.id, question=QUESTION,
            providers=["google_drive"], mentions=[mention], history=[],
        )
    assert not provider.synthesis_inputs and not provider.answer_calls
    assert "beta-denied-review.pdf" not in json.dumps(provider.classifier_inputs)


def test_cross_folder_inventory_reference_denied_in_same_org(semantic_session):
    case = make_case(semantic_session, listing=True)
    sibling = LibraryNode(organization_id=case.org.id, source_id=case.workspace.source_id,
                          parent_id=case.folder.parent_id, external_id="sibling-folder",
                          kind="folder", name="Outra pasta sintética")
    semantic_session.add(sibling)
    semantic_session.flush()
    case.nodes[1].parent_id = sibling.id
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied, match="outside the authorized selection"):
        LibraryService(semantic_session).catalog_file_snapshots(
            scope=case.scope, user_id=case.user.id, providers=case.providers,
            node_ids=[case.nodes[1].id], inventory_folder_ids={case.nodes[1].id: case.folder.id},
        )


def test_existing_fail_closed_for_listed_file_moved_outside_folder(semantic_session):
    case = make_case(semantic_session, listing=True)
    case.nodes[1].parent_id = None
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied, match="outside the authorized selection"):
        follow(case, Classifies(intent="summarize_files", target="previous_answer_files",
                               tool="summarize_documents"))


def test_coverage_listed_unindexed_file_requires_honest_warning(semantic_session):
    case = make_case(semantic_session, listing=True)
    case.docs[1].index_status = "failed"
    semantic_session.commit()
    provider = Classifies(intent="summarize_files", target="previous_answer_files", tool="summarize_documents")
    result = follow(case, provider)
    answer = result.answer or ""
    assert {c.document_id for c in result.citations} == {case.docs[0].id}
    # Accept a safe count-based notice or a named authorized-file notice; do not
    # prescribe an internal field or force a particular UI sentence.
    notice = re.search(r"sem (?:conteúdo |texto )?(?:indexad|índice)|não (?:está|foi|há|tem).*indexad|"
                       r"não indexad|falha.*(?:extração|indexação)|não.*(?:consegui|possível).*ler", answer, re.IGNORECASE)
    assert notice, "SPEC F-B: one listed file was omitted without an honest index/coverage warning"
    assert "beta-denied-review.pdf" in answer or re.search(r"\b1\b|\bum\b", answer, re.IGNORECASE)
    assert BETA not in answer


def test_unavailable_listed_name_not_disclosed_to_ai_or_error(semantic_session):
    case = make_case(semantic_session, listing=True)
    semantic_session.delete(case.nodes[1])
    semantic_session.commit()
    provider = RecordingAI()
    with pytest.raises(SyncAccessDenied) as error:
        follow(case, provider)
    assert "beta-denied-review.pdf" not in str(error.value)
    assert "beta-denied-review.pdf" not in json.dumps(provider.classifier_inputs), "F-A/B: unauthorized name in AI payload"
