"""The answer's presentation blocks: prompt vocabulary, and blocks surviving the grounded synthesis path."""

from sqlalchemy.orm import Session

from app.api.ingestion import _answer_without_source_links
from app.knowledge.questions import ANSWER_FORMAT_GUIDANCE, GeneratedAnswer, file_summary_instructions
from tests.unit.test_agent_flow import IntentProvider, _ask, _folder_with_files
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

BLOCK_ANSWER = (
    "A pasta tem dois arquivos [1].\n\n"
    "## Arquivos\n\n"
    "::: file Indexed.pdf\n"
    "Plano comercial que prioriza clientes existentes [1].\n"
    "- **Foco:** clientes existentes [1]\n"
    ":::\n\n"
    "::: file Not indexed.pdf\n"
    "Ainda não há conteúdo indexado para resumir.\n"
    ":::"
)


def test_guidance_offers_the_block_vocabulary_without_a_fixed_template() -> None:
    for convention in ("## Title", "::: file <exact file name>", "**Label:** value", "::: highlight", "::: steps"):
        assert convention in ANSWER_FORMAT_GUIDANCE
    assert "no fixed template" in ANSWER_FORMAT_GUIDANCE
    # Structure is presentation only: grounding and markers stay required.
    assert "state only what the sources support" in ANSWER_FORMAT_GUIDANCE
    assert "evidence marker" in ANSWER_FORMAT_GUIDANCE


def test_guidance_keeps_internal_language_out_and_is_honest_about_title_only_files() -> None:
    assert "no trecho fornecido" in ANSWER_FORMAT_GUIDANCE  # named as forbidden
    assert "never mention excerpts, chunks" in ANSWER_FORMAT_GUIDANCE
    assert "Só o título está indexado; não há conteúdo suficiente para resumir." in ANSWER_FORMAT_GUIDANCE
    assert "only its title, return an empty summary" in file_summary_instructions(350)
    assert "Never mention chunks" in file_summary_instructions(350)


def test_block_markers_survive_the_answer_sanitizer() -> None:
    answer = "::: file Profile.pdf\nCurrículo de engenheiro (fonte 1).\n:::\n\n::: highlight\nResumo.\n:::"
    assert _answer_without_source_links(answer) == answer
    # Punctuation-only leftovers are still dropped.
    assert _answer_without_source_links("Texto.\n;\nMais.") == "Texto.\n\nMais."


def test_block_formatted_synthesis_keeps_blocks_numbered_sources_and_citations(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, document = _folder_with_files(semantic_session)
    provider = IntentProvider(synthesis=GeneratedAnswer(BLOCK_ANSWER, [1]))

    result, _tool_results, _references = _ask(semantic_session, provider, folder, scope, user)

    assert "::: file Indexed.pdf" in result.answer and result.answer.count(":::\n") >= 1
    assert "(fonte 1)" in result.answer and "[1]" not in result.answer
    assert [item.document_name for item in result.citations] == ["Indexed.pdf"]
    assert result.citations[0].source_url
    # The API sanitizer leaves the rendered shape intact.
    assert _answer_without_source_links(result.answer) == result.answer


def test_unformatted_synthesis_still_answers_with_sources(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    provider = IntentProvider(synthesis=GeneratedAnswer("::: file sem fechamento\nTexto solto [1]", [1]))

    result, _tool_results, _references = _ask(semantic_session, provider, folder, scope, user)

    assert result.answer.startswith("::: file sem fechamento")
    assert result.citations and result.citations[0].document_name == "Indexed.pdf"


def test_guidance_keeps_labels_in_the_question_language_and_documents_tags() -> None:
    assert "language of the user's question" in ANSWER_FORMAT_GUIDANCE
    assert "never translate or alter values quoted from the documents" in ANSWER_FORMAT_GUIDANCE
    assert "' | '" in ANSWER_FORMAT_GUIDANCE and "tags" in ANSWER_FORMAT_GUIDANCE


def test_guidance_reserves_file_cards_for_per_file_requests_and_prefers_fluid_prose():
    assert "only when the user asks for the answer file by file" in ANSWER_FORMAT_GUIDANCE
    assert "do not split the answer by file" in ANSWER_FORMAT_GUIDANCE
    assert "fluid, direct prose" in ANSWER_FORMAT_GUIDANCE
    assert "cites each claim inline" in ANSWER_FORMAT_GUIDANCE
    assert "never repeat the same fact" in ANSWER_FORMAT_GUIDANCE
    assert "evidence marker" in ANSWER_FORMAT_GUIDANCE
