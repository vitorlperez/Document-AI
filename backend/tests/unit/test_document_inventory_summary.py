"""Functional checks for per-document synthesis and evidence evaluation."""

import pytest
from sqlalchemy.orm import Session

from app.knowledge.questions import (
    RETRIEVAL_STATUS_SUFFICIENT,
    AIProviderUnavailable,
    _is_document_inventory_summary_question,
)
from tests.unit.test_semantic_questions import FakeProvider, ask, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTIONS = [
    "Quais arquivos temos dentro dessa pasta e quais sao as principais informacoes dentro deles?",
    "Liste os documentos e resuma as principais informações de cada um",
    "Quais arquivos existem? Faça um resumo deles",
]


class SummaryProvider(FakeProvider):
    def __init__(self, claims=None, assessments=None, unavailable=False):
        super().__init__({})
        self.claims = claims
        self.assessments = assessments
        self.unavailable = unavailable
        self.summary_calls = []

    def summarize_documents(self, *, question, evidence):
        self.summary_calls.append((question, evidence))
        if self.unavailable:
            raise AIProviderUnavailable("offline")
        return self.claims(evidence) if callable(self.claims) else (self.claims or [])

    def assess_summary(self, *, claims, evidence):
        return self.assessments(claims) if callable(self.assessments) else (self.assessments or [])


def claim(evidence, index, text):
    return {"document_id": str(evidence[index - 1].document_id), "text": text, "passages": [index]}


@pytest.mark.parametrize("question", QUESTIONS)
def test_real_information_from_both_documents_is_summarized(
    semantic_session: Session,  # noqa: F811
    question: str,
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    faith = chunk(
        session,
        org,
        folder,
        name="A Gravidade do pecado de impuresa",
        text="O texto trata o pecado de impureza com temor e reverência, e aponta para a graça de Deus.",
    )
    profile = chunk(
        session,
        org,
        folder,
        name="Profile.pdf",
        text="Vitor tem cinco anos de experiência Full Stack com Python e Django. Trabalha com LLMs e arquitetura multi-tenant.",
    )
    provider = SummaryProvider(
        claims=lambda e: [
            claim(
                e,
                next(i for i, item in enumerate(e, 1) if item.document_id == faith.document_id),
                "O texto relaciona impureza a temor, reverência e graça de Deus.",
            ),
            claim(
                e,
                next(i for i, item in enumerate(e, 1) if item.document_id == profile.document_id),
                "O perfil relata cinco anos de experiência Full Stack com Python e Django, além de LLMs e arquitetura multi-tenant.",
            ),
        ],
        assessments=lambda claims: [
            {"claim_index": i, "verdict": "supported"} for i in range(1, len(claims) + 1)
        ],
    )
    result = ask(session, provider, org, user, folder, question)
    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert "temor, reverência e graça de Deus" in result.answer
    assert "cinco anos de experiência Full Stack" in result.answer
    assert "LLMs e arquitetura multi-tenant" in result.answer
    assert "Cobertura da síntese avaliada: 2 de 2" in result.answer
    assert {item.document_id for item in result.citations} == {
        faith.document_id,
        profile.document_id,
    }
    assert len(provider.summary_calls) == 1


@pytest.mark.parametrize(
    "bad_claim",
    [
        "Vitor não tem cinco anos de experiência Full Stack com Python e Django.",
        "Vitor tem cinco anos de experiência Full Stack com Python e Django e fundou uma empresa milionária.",
        "Os dados são insuficientes para resumir o perfil.",
    ],
)
def test_unsupported_or_caveat_claim_gets_local_labelled_fallback(
    semantic_session: Session,  # noqa: F811
    bad_claim: str,
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(
        session,
        org,
        folder,
        name="Profile.pdf",
        text="Vitor tem cinco anos de experiência Full Stack com Python e Django em Manaus.",
    )
    provider = SummaryProvider(
        claims=lambda e: [claim(e, 1, bad_claim)],
        assessments=[{"claim_index": 1, "verdict": "unsupported"}],
    )
    result = ask(session, provider, org, user, folder, QUESTIONS[0])
    assert bad_claim not in result.answer
    assert "Trecho literal (síntese sem suporte nesta afirmação)" in result.answer
    assert "Cobertura da síntese avaliada: 0 de 1" in result.answer
    assert "1 com recuo extrativo" in result.answer


def test_duplicate_names_remain_separate_and_cross_document_claim_rejected(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    first = chunk(
        session, org, folder, name="Profile.pdf", text="Ana trabalha com Python em Belém."
    )
    second = chunk(session, org, folder, name="Profile.pdf", text="Bruno escreve Java em Manaus.")
    provider = SummaryProvider(
        claims=lambda e: [
            claim(e, 1, "Ana trabalha com Python em Belém."),
            {
                "document_id": str(e[0].document_id),
                "text": "Bruno escreve Java em Manaus.",
                "passages": [2],
            },
        ],
        assessments=[{"claim_index": 1, "verdict": "supported"}],
    )
    result = ask(session, provider, org, user, folder, QUESTIONS[0])
    assert result.answer.count("Profile.pdf (fonte") >= 4
    assert "Ana trabalha com Python" in result.answer
    assert "Bruno escreve Java" not in result.answer  # short source cannot become a summary
    assert "Cobertura da síntese avaliada: 1 de 2" in result.answer
    assert {item.document_id for item in result.citations} == {
        first.document_id,
        second.document_id,
    }


def test_provider_outage_retains_inventory_and_local_extract(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(
        session,
        org,
        folder,
        name="Briefing.pdf",
        text="The launch is planned for September and the campaign targets existing customers.",
    )
    result = ask(session, SummaryProvider(unavailable=True), org, user, folder, QUESTIONS[0])
    assert "Briefing.pdf" in result.answer
    assert "Trecho literal" in result.answer
    assert "Cobertura da síntese avaliada: 0 de 1" in result.answer


def test_passage_selection_prefers_substance_and_preserves_sentence_boundary(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    first = chunk(session, org, folder, name="Report.pdf", text="Report.pdf")
    from app.knowledge.models import DocumentChunk
    from app.knowledge.questions import EMBEDDING_MODEL

    session.add(
        DocumentChunk(
            organization_id=org.id,
            workspace_folder_id=folder.id,
            document_id=first.document_id,
            position=1,
            text="The report describes a five-year plan for regional expansion and identifies three operational priorities.",
            search_text="regional expansion priorities",
            embedding=[1, 0],
            embedding_model=EMBEDDING_MODEL,
        )
    )
    session.commit()
    provider = SummaryProvider()
    ask(session, provider, org, user, folder, QUESTIONS[0])
    assert "five-year plan" in provider.summary_calls[0][1][0].excerpt
    assert provider.summary_calls[0][1][0].excerpt.endswith("priorities.")


def test_topical_information_lookup_is_not_misclassified_as_inventory_summary() -> None:
    assert not _is_document_inventory_summary_question(
        "Quais arquivos têm informações sobre Vitor?"
    )


@pytest.mark.parametrize(
    "question",
    [
        "Estruture melhor o resumo do conteudo do arquivo",
        "Faça um resumo desse documento",
    ],
)
def test_file_scoped_summary_follow_up_does_not_depend_on_semantic_threshold(
    semantic_session: Session,  # noqa: F811
    question: str,
) -> None:
    # Second message of the reported chat: a file mention (Profile.pdf) plus a
    # summary request without listing words. The question is about the file,
    # not a topic, so its embedding never clears the relevance threshold.
    from app.core.scoping import OrganizationScope
    from app.knowledge.questions import QuestionService

    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="A Gravidade do pecado de impuresa", text="Texto sobre impureza.")
    profile = chunk(
        session,
        org,
        folder,
        name="Profile.pdf",
        text="Vitor tem cinco anos de experiência Full Stack com Python e Django.",
        embedding=[0.0, 1.0],
    )
    provider = SummaryProvider(
        claims=lambda e: [claim(e, 1, "O perfil relata cinco anos de experiência Full Stack com Python e Django.")],
        assessments=[{"claim_index": 1, "verdict": "supported"}],
    )
    provider.vectors = {question: [1.0, 0.0]}
    result = QuestionService(session, provider).ask(
        scope=OrganizationScope(org.id),
        user_id=user.id,
        workspace_folder_ids=[folder.id],
        document_ids={profile.document_id},
        question=question,
    )
    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert result.answer and "cinco anos de experiência Full Stack" in result.answer
    assert {item.document_id for item in result.citations} == {profile.document_id}
    assert "impureza" not in result.answer


def test_file_scoped_fact_question_still_uses_relevance() -> None:
    from app.knowledge.questions import _is_selection_summary_question

    assert _is_selection_summary_question("Estruture melhor o resumo do conteudo do arquivo")
    assert not _is_selection_summary_question("Qual o principal cliente citado no arquivo?")
    assert not _is_selection_summary_question("Quando foi o resumo de vendas publicado? Qual a data?")
