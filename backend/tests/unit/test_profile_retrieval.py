"""Profile.pdf regressions: real indexed text, deterministic embeddings and mocked LLM."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.knowledge.models import DocumentChunk
from app.knowledge.questions import (
    EMBEDDING_MODEL,
    Evidence,
    QuestionService,
    _document_summary_evidence,
    _select_diverse_evidence,
)
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


@pytest.fixture
def profile(semantic_session):  # noqa: F811 - imported pytest fixture
    session = semantic_session
    org, user, folder = context(session)
    data = json.loads((Path(__file__).parents[1] / "fixtures/profile_chunks.json").read_text())
    first = chunk(session, org, folder, name="Profile.pdf", text=data[0]["text"])
    first.page_number = data[0]["page_number"]
    chunks = [first]
    for raw in data[1:]:
        item = DocumentChunk(
            organization_id=org.id, workspace_folder_id=folder.id,
            document_id=first.document_id, position=raw["position"], text=raw["text"],
            search_text=f"Profile.pdf\n{raw['text']}", page_number=raw["page_number"],
            embedding=[1, 0], embedding_model=EMBEDDING_MODEL,
        )
        session.add(item)
        chunks.append(item)
    session.commit()
    return session, org, user, folder, chunks


def run_profile(profile, question, *, selected_file=True):
    session, org, user, folder, chunks = profile
    provider = FakeProvider({question: [1, 0]}, answer="Allstacks desde junho de 2025 [1].")
    from app.core.scoping import OrganizationScope

    result = QuestionService(session, provider).ask(
        scope=OrganizationScope(org.id), user_id=user.id, workspace_folder_id=folder.id,
        document_ids={chunks[0].document_id} if selected_file else None,
        question=question, answer_mode="relevance",
    )
    return result, provider.answer_calls[0][1]


@pytest.mark.parametrize("question", [
    "Em quais empresas o Vitor trabalhou e quando?",
    "Qual foi o último emprego do Vitor?",
    "Quanto tempo o Vitor trabalhou na Estoca?",
])
def test_profile_content_keeps_full_chunks_latest_job_and_document_order(profile, question):
    result, evidence = run_profile(profile, question)
    text = "\n".join(item.excerpt for item in evidence)
    for item in profile[-1]:
        assert item.text in text  # Includes facts beyond 500 characters and chunk tails.
    assert len(evidence) == 1  # All relevant adjacent pages become one continuous passage.
    assert evidence[0].chunk_ids == tuple(item.id for item in profile[-1])
    assert text.index("Allstacks") < text.index("Estoca") < text.index("Cloudiabot") < text.index("Wasion International")
    assert "June 2025 - Present (8 months)" in text
    assert "February 2023 - June 2025 (2 years 5 months)" in text
    assert result.citations[0].source_url == "https://drive.example.test/Profile.pdf"
    assert "(fonte 1)" in result.answer


def test_bounded_neighbors_rescue_below_threshold_continuation(profile):
    session, _org, _user, _folder, chunks = profile
    for item in chunks:
        item.embedding = [0, 1]
    chunks[2].embedding = [1, 0]
    session.commit()
    _, evidence = run_profile(profile, "Quando ocorreu essa experiência profissional?", selected_file=False)
    text = "\n".join(item.excerpt for item in evidence)
    assert chunks[1].text in text  # Allstacks: below threshold, beside the strongest seed.
    assert chunks[3].text in text
    assert chunks[0].text not in text  # Expansion is bounded; it cannot recursively flood a file.
    assert chunks[4].text not in text


def passage(text, position, score=0.9, document_id=None):
    item = Evidence(document_id or uuid4(), "Profile.pdf", uuid4(), text, position + 1,
                    "https://drive.example.test/Profile.pdf", score)
    return replace(item, chunk_ids=(item.chunk_id,), chunk_positions=(position,))


def test_adjacent_overlap_is_removed_but_distinct_facts_are_merged_in_order():
    first = passage("Allstacks June 2025. Python Django and PostgreSQL.", 1)
    second = passage("Python Django and PostgreSQL. Estoca February 2023.", 2,
                     score=1.0, document_id=first.document_id)
    selected = _select_diverse_evidence([second, first])
    assert len(selected) == 1
    assert selected[0].excerpt == "Allstacks June 2025. Python Django and PostgreSQL. Estoca February 2023."
    assert selected[0].chunk_ids == (first.chunk_id, second.chunk_id)


def test_nonadjacent_shared_vocabulary_is_not_deduplicated():
    first = passage("Python Django team. Allstacks June 2025.", 1)
    second = passage("Python Django team. Wasion January 2021.", 4, document_id=first.document_id)
    assert len(_select_diverse_evidence([second, first])) == 2


def test_budget_prioritizes_score_without_cutting_a_chunk_that_fits():
    first = passage("Low score. " * 100, 0, score=0.5)
    second = passage("High score with a factual tail. " * 40, 1, score=0.9)
    selected = _select_diverse_evidence([first, second], max_chars=1400)
    assert len(selected) == 1
    assert selected[0].excerpt == second.excerpt
    assert selected[0].chunk_id == second.chunk_id


def test_summary_no_longer_discards_adjacent_distinct_jobs(profile):
    session, _org, _user, folder, chunks = profile
    from app.knowledge.models import Document

    document = session.get(Document, chunks[0].document_id)
    evidence = _document_summary_evidence([(document, item) for item in chunks],
                                          {folder.id: "google"}, "Resumo do Profile.pdf")
    assert "Allstacks" in "\n".join(item.excerpt for item in evidence)
    assert "Wasion International" in "\n".join(item.excerpt for item in evidence)
    assert len(evidence) == 1
    assert evidence[0].chunk_ids == tuple(item.id for item in chunks)


def test_redundant_nonadjacent_chunk_does_not_bridge_a_gap():
    first = passage("Shared factual passage.", 1)
    second = passage("Intervening unique fact.", 2, document_id=first.document_id)
    duplicate = passage(first.excerpt, 4, document_id=first.document_id)
    later = passage("Later unique fact.", 5, document_id=first.document_id)
    selected = _select_diverse_evidence([later, duplicate, second, first])
    assert len(selected) == 2
    assert selected[0].excerpt == first.excerpt + "\n" + second.excerpt
    assert selected[1].excerpt == later.excerpt


def test_selected_file_is_read_even_when_every_embedding_is_below_threshold(profile):
    session, _org, _user, _folder, chunks = profile
    for item in chunks:
        item.embedding = [0, 1]
    session.commit()
    result, evidence = run_profile(profile, "Quanto tempo trabalhou na Estoca?")
    assert result.confidence == "supported"
    assert chunks[2].text in evidence[0].excerpt


def test_folder_scoping_still_uses_relevance_gate(profile):
    session, org, user, folder, chunks = profile
    for item in chunks:
        item.embedding = [0, 1]
    session.commit()
    question = "Quanto custa a aquisição?"
    provider = FakeProvider({question: [1, 0]})
    from app.core.scoping import OrganizationScope

    result = QuestionService(session, provider).ask(
        scope=OrganizationScope(org.id), user_id=user.id, workspace_folder_id=folder.id,
        document_ids={chunks[0].document_id}, read_selected_documents=False,
        question=question, answer_mode="relevance",
    )
    assert result.retrieval_status == "below_evidence_threshold"
    assert provider.answer_calls == []


def test_configured_budget_reaches_provider_and_preserves_summary_target(monkeypatch):
    from app.core.config import Settings
    from app.knowledge.questions import OpenAIQuestionProvider

    monkeypatch.setenv("EVIDENCE_CONTEXT_CHARS", "20000")
    settings = Settings(_env_file=None, database_url="postgresql://test:test@localhost/test")
    provider = OpenAIQuestionProvider(None, evidence_context_chars=settings.evidence_context_chars)
    assert QuestionService(None, provider).evidence_context_chars == 20000
    assert settings.agent_file_summary_chars == 350


def test_synthesis_request_contains_full_evidence_and_allows_cited_enumeration(profile, monkeypatch):
    from app.knowledge.questions import OpenAIQuestionProvider

    _, evidence = run_profile(profile, "Em quais empresas trabalhou?")
    requests = []

    def post(_endpoint, payload):
        requests.append(payload)
        return {"output_text": '{"answer":"Allstacks [1].","citations":[1]}'}

    provider = OpenAIQuestionProvider(None)
    monkeypatch.setattr(provider, "_post", post)
    provider.answer(question="Em quais empresas trabalhou?", evidence=evidence)
    assert evidence[0].excerpt in requests[0]["input"]
    assert "chronologically organize" in requests[0]["instructions"]
    assert "Every factual claim needs a cited source number" in requests[0]["instructions"]
    assert "interface renders source links separately" in requests[0]["instructions"]
