"""Compound document inventory with bounded, extractive evidence."""

import pytest
from sqlalchemy.orm import Session

from app.knowledge.questions import (
    RETRIEVAL_STATUS_SUFFICIENT,
    GeneratedAnswer,
    _is_document_inventory_summary_question,
)
from tests.unit.test_semantic_questions import FakeProvider, ask, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTION = "Liste os arquivos e resuma as principais informações deles"


def test_compound_inventory_renders_authorized_excerpts_without_calling_provider(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    first = chunk(
        session, org, folder, name="Faith notes.pdf", text="A impureza causa impacto comunitário."
    )
    second = chunk(
        session, org, folder, name="Profile.pdf", text="Vitor é engenheiro de software em Manaus."
    )
    provider = FakeProvider({}, answer="Uma síntese inventada [1].", citations=[1])

    result = ask(session, provider, org, user, folder, QUESTION)

    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert provider.embed_calls == []
    assert provider.answer_calls == []
    assert "Arquivos encontrados no conteúdo indexado (2)" in result.answer
    assert "Faith notes.pdf (fonte 1)" in result.answer
    assert "Profile.pdf (fonte 2)" in result.answer
    assert "> A impureza causa impacto comunitário." in result.answer
    assert "> Vitor é engenheiro de software em Manaus." in result.answer
    assert "extração literal; não é resumo semântico" in result.answer
    assert "Cobertura da evidência extrativa: 2 de 2 arquivos" in result.answer
    assert {item.document_id for item in result.citations} == {
        first.document_id,
        second.document_id,
    }


@pytest.mark.parametrize(
    "generated_claim",
    [
        "Profile.pdf afirma que Vitor não é engenheiro de software em Manaus [1].",
        "Profile.pdf afirma que Vitor é engenheiro de software em Manaus e fundou uma empresa milionária [1].",
        "Profile.pdf afirma que Vitor é engenheiro de software em Manaus e é bilionário [1].",
    ],
)
def test_compound_inventory_never_renders_generated_claims(
    semantic_session: Session,  # noqa: F811
    generated_claim: str,
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(
        session, org, folder, name="Profile.pdf", text="Vitor é engenheiro de software em Manaus."
    )
    provider = FakeProvider({}, answer=generated_claim, citations=[1])

    result = ask(session, provider, org, user, folder, QUESTION)

    assert provider.answer_calls == []
    assert generated_claim not in result.answer
    assert "não é engenheiro" not in result.answer
    assert "empresa milionária" not in result.answer
    assert "bilionário" not in result.answer
    assert "> Vitor é engenheiro de software em Manaus." in result.answer
    assert "Cobertura da evidência extrativa: 1 de 1 arquivos" in result.answer


def test_compound_inventory_counts_only_documents_with_nonempty_excerpts(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(
        session, org, folder, name="Faith notes.pdf", text="A impureza causa impacto comunitário."
    )
    chunk(session, org, folder, name="Empty.pdf", text="")

    result = ask(session, FakeProvider({}), org, user, folder, QUESTION)

    assert "Empty.pdf (fonte 1)" in result.answer
    assert "Sem trecho extraível nesta resposta" in result.answer
    assert "Cobertura da evidência extrativa: 1 de 2 arquivos" in result.answer


def test_compound_inventory_keeps_same_named_documents_distinct_by_document_id(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    first = chunk(session, org, folder, name="Profile.pdf", text="Ana trabalha com Python.")
    second = chunk(session, org, folder, name="Profile.pdf", text="Bruno escreve Java em Belém.")

    result = ask(session, FakeProvider({}), org, user, folder, QUESTION)

    assert result.answer.count("- Profile.pdf (fonte") == 4
    assert "- Profile.pdf (fonte 1)" in result.answer
    assert "- Profile.pdf (fonte 2)" in result.answer
    assert "> Ana trabalha com Python." in result.answer
    assert "> Bruno escreve Java em Belém." in result.answer
    assert {item.document_id for item in result.citations} == {
        first.document_id,
        second.document_id,
    }
    assert "Cobertura da evidência extrativa: 2 de 2 arquivos" in result.answer


def test_extractive_evidence_preserves_source_markers_and_line_breaks(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    source_text = "Passo [1]: validar entrada.\nPasso [2]: persistir saída."
    chunk(session, org, folder, name="Runbook.md", text=source_text)

    result = ask(session, FakeProvider({}), org, user, folder, QUESTION)

    assert "> Passo [1]: validar entrada.\n> Passo [2]: persistir saída." in result.answer


def test_compound_inventory_does_not_depend_on_provider_availability(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Briefing.pdf", text="The launch is planned for September.")
    provider = FakeProvider({})

    def unavailable(**_kwargs: object) -> GeneratedAnswer:
        raise AssertionError("the extractive path must not call the model provider")

    provider.answer = unavailable  # type: ignore[method-assign]

    result = ask(session, provider, org, user, folder, QUESTION)

    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert "> The launch is planned for September." in result.answer
    assert "Cobertura da evidência extrativa: 1 de 1 arquivos" in result.answer


def test_topical_information_lookup_is_not_misclassified_as_inventory_summary() -> None:
    assert not _is_document_inventory_summary_question(
        "Quais arquivos têm informações sobre Vitor?"
    )
