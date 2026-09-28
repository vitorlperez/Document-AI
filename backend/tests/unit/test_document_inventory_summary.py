"""Compound document inventory and content-summary behavior."""

from sqlalchemy.orm import Session

from app.knowledge.questions import (
    RETRIEVAL_STATUS_SUFFICIENT,
    AIProviderUnavailable,
    GeneratedAnswer,
    _is_document_inventory_summary_question,
)
from tests.unit.test_semantic_questions import (
    FakeProvider,
    ask,
    chunk,
    context,
)
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


def test_compound_inventory_summary_uses_each_scoped_document_without_query_embedding(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    first = chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    second = chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {},
        answer=(
            "Faith notes.pdf explica efeitos comunitários [1]. "
            "Profile.pdf apresenta a atuação profissional de Vitor [2]."
        ),
        citations=[1, 2],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Quais arquivos temos dentro dessa pasta e quais sao as principais informacoes dentro deles?",
    )

    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert provider.embed_calls == []
    assert {item.document_id for item in provider.answer_calls[0][1]} == {
        first.document_id,
        second.document_id,
    }
    assert "Arquivos encontrados no conteúdo indexado (2)" in result.answer
    assert "Faith notes.pdf (fonte 1)" in result.answer
    assert "Profile.pdf (fonte 2)" in result.answer
    assert "Cobertura da síntese: 2 de 2 arquivos" in result.answer


def test_compound_inventory_summary_keeps_useful_partial_answer_and_names_missing_document(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {}, answer="Faith notes.pdf descreve um impacto comunitário [1].", citations=[1]
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert result.confidence == "supported"
    assert "Faith notes.pdf descreve um impacto comunitário (fonte 1)" in result.answer
    assert "Sem síntese verificável nesta resposta" in result.answer
    assert "Profile.pdf (fonte 2)" in result.answer
    assert "Cobertura da síntese: 1 de 2 arquivos" in result.answer


def test_compound_inventory_summary_ignores_declared_index_without_supported_claim(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {},
        answer=(
            "Faith notes.pdf descreve um impacto comunitário [1]. "
            "Profile.pdf afirma que Vitor fundou uma empresa."
        ),
        citations=[1, 2],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert "Faith notes.pdf descreve um impacto comunitário (fonte 1)" in result.answer
    assert "fundou uma empresa" not in result.answer
    assert "Profile.pdf (fonte 2)" in result.answer
    assert "Cobertura da síntese: 1 de 2 arquivos" in result.answer


def test_compound_inventory_summary_does_not_count_a_title_only_citation_as_summary(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {},
        answer="Faith notes.pdf descreve um impacto comunitário [1]. Profile.pdf [2].",
        citations=[1, 2],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert "Principais informações" in result.answer
    summary_section = result.answer.split(
        "Principais informações encontradas nos trechos consultados:", maxsplit=1
    )[1].split("Sem síntese verificável", maxsplit=1)[0]
    assert "Profile.pdf" not in summary_section
    assert "Cobertura da síntese: 1 de 2 arquivos" in result.answer


def test_compound_inventory_summary_filters_invalid_and_duplicate_declared_indexes(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {},
        answer="Faith notes.pdf descreve um impacto comunitário [1]. Profile.pdf [99].",
        citations=[1, 1, 99, 2],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert "Faith notes.pdf descreve um impacto comunitário (fonte 1)" in result.answer
    assert "[99]" not in result.answer
    assert "Cobertura da síntese: 1 de 2 arquivos" in result.answer


def test_compound_inventory_summary_rejects_citation_from_a_different_document(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Profile.pdf", text="Vitor is a software engineer in Manaus.")
    provider = FakeProvider(
        {},
        answer="Profile.pdf afirma que Vitor fundou uma empresa [1].",
        citations=[1],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert "fundou uma empresa" not in result.answer
    assert "Cobertura da síntese: 0 de 2 arquivos" in result.answer


def test_compound_inventory_summary_does_not_verify_claim_from_empty_excerpt(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Faith notes.pdf", text="Impurity harms the whole community.")
    chunk(session, org, folder, name="Empty.pdf", text="")
    provider = FakeProvider(
        {},
        answer=(
            "Faith notes.pdf descreve um impacto comunitário [2]. "
            "Empty.pdf descreve uma aquisição milionária [1]."
        ),
        citations=[1, 2],
    )

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Liste os arquivos e resuma as principais informações deles",
    )

    assert "aquisição milionária" not in result.answer
    assert "Empty.pdf (fonte 1)" in result.answer
    assert "Cobertura da síntese: 1 de 2 arquivos" in result.answer


def test_compound_inventory_summary_returns_verified_inventory_when_generation_is_invalid(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Briefing.pdf", text="The launch is planned for September.")
    provider = FakeProvider({}, answer="Insufficient evidence.", citations=[])

    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Quais documentos existem e qual o resumo do conteúdo deles?",
    )

    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert result.answer is not None
    assert "Briefing.pdf (fonte 1)" in result.answer
    assert "Sem síntese verificável nesta resposta" in result.answer
    assert "Cobertura da síntese: 0 de 1 arquivos" in result.answer


def test_compound_inventory_summary_degrades_to_inventory_when_provider_is_unavailable(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    org, user, folder = context(session)
    chunk(session, org, folder, name="Briefing.pdf", text="The launch is planned for September.")
    provider = FakeProvider({})

    def unavailable(**_kwargs: object) -> GeneratedAnswer:
        raise AIProviderUnavailable("provider timed out")

    provider.answer = unavailable  # type: ignore[method-assign]
    result = ask(
        session,
        provider,
        org,
        user,
        folder,
        "Quais documentos existem e qual o resumo do conteúdo deles?",
    )

    assert result.retrieval_status == RETRIEVAL_STATUS_SUFFICIENT
    assert "Briefing.pdf (fonte 1)" in result.answer
    assert "Sem síntese verificável nesta resposta" in result.answer


def test_topical_information_lookup_is_not_misclassified_as_inventory_summary() -> None:
    assert not _is_document_inventory_summary_question(
        "Quais arquivos têm informações sobre Vitor?"
    )
