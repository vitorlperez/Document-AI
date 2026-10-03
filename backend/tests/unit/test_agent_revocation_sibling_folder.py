"""Regression: a denied folder must not keep its answers alive because a sibling folder is ready.

Same harness as test_agent_revocation_review (real services, synthetic SQLite, fake AI that
echoes memory). Two sync spaces share one source; the one behind the earlier answer stops
being admitted while the other stays queryable.
"""

# Pytest intentionally injects the imported fixture under the same parameter name.
# ruff: noqa: F811

import json
from uuid import uuid4

from app.knowledge.agent import ConversationService
from app.workspaces.models import WorkspaceFolder
from tests.unit.test_agent_revocation_review import (
    BETA,
    DENIALS,
    OLD_SAFE,
    PREVIOUS,
    RecordingAI,
    follow,
    make_case,
    no_external_ai,  # noqa: F401
    semantic_session,  # noqa: F401
)
from tests.unit.test_semantic_questions import chunk

SIBLING_TEXT = "GAMMA-SIBLING-CURRENT: texto da pasta irmã."


def sibling_case(session, *, deny_folder=True):
    case = make_case(session, answer_override=PREVIOUS)
    sibling = WorkspaceFolder(
        organization_id=case.org.id, source_id=case.workspace.source_id,
        external_folder_id=str(uuid4()), name="Pasta irmã", uniform_access_confirmed=True, status="ready",
    )
    session.add(sibling)
    session.flush()
    chunk(session, case.org, sibling, name="gamma-sibling.pdf", text=SIBLING_TEXT)
    if deny_folder:
        case.workspace.status = "disconnected"  # folder admission denied; the source stays connected
    session.commit()
    return case


def test_denied_folder_with_ready_sibling_keeps_old_answer_away_from_ai(semantic_session):
    case = sibling_case(semantic_session)
    provider = RecordingAI()
    try:
        follow(case, provider)
    except (*DENIALS, ValueError):
        pass  # a current denial is allowed; derived text must not reach the AI before it
    payload = json.dumps(
        [provider.classifier_inputs, provider.synthesis_inputs], ensure_ascii=False, default=str,
    )
    assert OLD_SAFE not in payload, "denied folder: old answer reached the AI because a sibling is ready"
    assert BETA not in payload, "denied folder: derived text of the denied folder reached the AI"


def test_admitted_folder_with_sibling_keeps_continuity(semantic_session):
    # Control: nothing is denied, so the earlier answer must still reach the classifier.
    case = sibling_case(semantic_session, deny_folder=False)
    provider = RecordingAI()
    follow(case, provider)
    assert PREVIOUS in [m["content"] for call in provider.classifier_inputs for m in call["history"]]


def test_listed_but_uncited_withdrawn_file_excludes_the_answer(semantic_session):
    # The answer cites only A; B appears just as a listed reference and its document was withdrawn.
    case = make_case(semantic_session, listing=True, answer_override=PREVIOUS)
    case.history[-1].response = {"citations": [{"document_id": str(case.docs[0].id)}]}
    case.docs[1].index_status = "deleted"
    semantic_session.commit()
    provider = RecordingAI()
    follow(case, provider)
    payload = json.dumps(provider.classifier_inputs, ensure_ascii=False)
    assert OLD_SAFE not in payload and "beta-denied-review.pdf" not in payload


def test_names_hidden_only_when_the_listing_answer_itself_is_excluded(semantic_session):
    case = make_case(semantic_session)
    conversations = ConversationService(semantic_session)
    alpha = case.nodes[0]
    conversations.append(
        conversation=case.conversation, role="user", content="Liste", context={"mentions": []},
    )
    conversations.append(
        conversation=case.conversation, role="assistant", content="Lista: alpha-review.pdf",
        context={"references": [{
            "id": str(alpha.id), "kind": "file", "name": alpha.name, "folder_id": str(case.folder.id),
        }]},
        response={"citations": [{"document_id": str(case.docs[0].id)}]},
    )
    conversations.append(
        conversation=case.conversation, role="user", content="E o orçamento?", context={"mentions": []},
    )
    conversations.append(
        conversation=case.conversation, role="assistant", content=PREVIOUS,
        context={"references": []}, response={"citations": [{"document_id": str(case.docs[1].id)}]},
    )
    semantic_session.delete(case.nodes[1])  # B, cited only by the last answer, is gone
    semantic_session.commit()
    _, case.history = conversations.history(
        scope=case.scope, user_id=case.user.id, conversation_id=case.conversation.id,
    )
    provider = RecordingAI()
    follow(case, provider)
    payload = json.dumps(provider.classifier_inputs, ensure_ascii=False)
    assert OLD_SAFE not in payload and BETA not in payload
    assert provider.classifier_inputs[0]["context"]["previous_answer_listed_files"] == ["alpha-review.pdf"]
