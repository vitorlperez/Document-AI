"""Per-file summaries of catalog answers: one batched, grounded LLM call with a sentence-bounded fallback."""

import json
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.agent import (
    AgentLimits,
    AgentService,
    FileSummaries,
    _catalog_item_row,
    _complete_summary,
    _sentence_preview,
)
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import (
    _REQUEST_DEADLINE,
    EMBEDDING_MODEL,
    FILE_SUMMARY_SCHEMA,
    AIProviderUnavailable,
    OpenAIQuestionProvider,
)
from app.library.models import LibraryNode
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTION = "Quais arquivos temos nessa pasta e me de uma explicacao resumida sobre o conteudo de cada arquivo"

# The wall of text of the reported screenshot: Profile.pdf's first indexed chunk.
PROFILE_CHUNK = (
    "Contact vitorlperez1@gmail.com perez-1992a01a4 (LinkedIn) Top Skills Grafana LLM Generative AI "
    "Languages Inglês (Full Professional) Certifications Python & MySQL Git completo: Do básico ao avançado "
    "Vitor Perez Software Engineer | Back-end | Python | LLM's | Generative AI | Django | Fast API | AWS | "
    "CI/CD Manaus, Amazonas, Brazil Summary I am a Full Stack Software Engineer with 5 years of experience "
    "specializing in Python, particularly with frameworks like Django and FastAPI. Throughout my career, I "
    "have worked across diverse industries, including AI and generative systems, chatbot automation, "
    "logistics, and manufacturing, where I've gained valuable hands-on experience building scalable, "
    "efficient, and reliable systems. My journey has equipped me with a unique skill set in both backend "
    "and frontend development, with recent focus on AI-driven solutions. Key Strengths: - AI & Innovation: "
    "Experience implementing LLMs and LangChain for practical AI solutions, enhancing user experiences "
    "through intelligent automation and generative systems. Page 1 of 5"
)
PROFILE_SECOND_CHUNK = "Experience Allstacks Software Engineer building AI agents for engineering analytics."
GRAVIDADE_CHUNK = "A GRAVIDADE DO PECADO DE IMPUREZA"


class InventoryClassifier(FakeProvider):
    """Mocked classifier: the message asks for the folder's files and what each one is about."""

    def classify_intent(self, *, question, history, context, model="gpt-5-nano"):
        return {
            "intent": "list_files_with_summaries", "target": "mentioned", "ordinals": [],
            "tool": "list_folder_inventory", "query": "",
        }


class BriefProvider(InventoryClassifier):
    """Mocked LLM: records every batched call and returns canned summaries by file number."""

    def __init__(self, replies: dict[int, str] | Exception) -> None:
        super().__init__({})
        self.replies = replies
        self.calls: list[dict[str, object]] = []

    def summarize_file_briefs(self, *, question, files, target_chars, model="gpt-5-nano"):
        self.calls.append({
            "question": question, "files": files, "target_chars": target_chars, "model": model,
            "deadline": _REQUEST_DEADLINE.get(),
        })
        if isinstance(self.replies, Exception):
            raise self.replies
        return self.replies


def _folder_with_files(session: Session):
    organization, user, workspace = context(session)
    profile = chunk(session, organization, workspace, name="Profile.pdf", text=PROFILE_CHUNK)
    session.add(DocumentChunk(
        organization_id=organization.id, workspace_folder_id=workspace.id, document_id=profile.document_id,
        position=1, text=PROFILE_SECOND_CHUNK, search_text=PROFILE_SECOND_CHUNK,
        embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL,
    ))
    gravidade = chunk(session, organization, workspace, name="A Gravidade.pdf", text=GRAVIDADE_CHUNK)
    # Indexed, but no chunk came out of it: there is nothing to summarize.
    empty = Document(
        organization_id=organization.id, workspace_folder_id=workspace.id, external_file_id=str(uuid4()),
        name="Vazio.pdf", mime_type="application/pdf", source_url="https://drive.example.test/Vazio.pdf",
        content_hash="b" * 64, processing_version="v1", index_status="indexed",
    )
    session.add(empty)
    session.flush()
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    folder = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id="docs", kind="folder", name="Docs",
    )
    session.add(folder)
    session.flush()
    external_ids = {
        "A Gravidade.pdf": session.get(Document, gravidade.document_id).external_file_id,
        "Profile.pdf": session.get(Document, profile.document_id).external_file_id,
        "Vazio.pdf": empty.external_file_id,
    }
    session.add_all([
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=external_id, kind="file", name=name,
        )
        for name, external_id in external_ids.items()
    ])
    session.commit()
    return OrganizationScope(organization.id), user, folder


def _ask(session: Session, provider, folder, scope, user, summaries: FileSummaries | None = None):
    return AgentService(session, provider, AgentLimits(), file_summaries=summaries).ask(
        scope=scope, user_id=user.id, question=QUESTION, providers=["google_drive"],
        mentions=[("folder", folder.id)], history=[],
    )


def _row(answer: str, name: str) -> str:
    return next(line for line in answer.splitlines() if line.startswith(f"- {name}:"))


def test_prompt_asks_for_a_target_length_in_one_schema_bound_call(monkeypatch) -> None:
    provider = OpenAIQuestionProvider("key")
    bodies: list[dict[str, object]] = []
    reply = {"summaries": [
        {"file": 2, "summary": "Currículo de engenheiro de software focado em Python e IA."},
        {"file": 1, "summary": "Título de um texto sobre a gravidade do pecado de impureza."},
        {"file": 9, "summary": "Fora do intervalo."},
    ]}

    def fake_post(path, body):
        bodies.append(body)
        return {"output": [{"content": [{"type": "output_text", "text": json.dumps(reply)}]}]}

    monkeypatch.setattr(provider, "_post", fake_post)
    files = [
        {"name": "A Gravidade.pdf", "chunks": [GRAVIDADE_CHUNK]},
        {"name": "Profile.pdf", "chunks": [PROFILE_CHUNK, PROFILE_SECOND_CHUNK]},
        {"name": "Outro.pdf", "chunks": ["Ata da reunião de março."]},
    ]
    summaries = provider.summarize_file_briefs(question=QUESTION, files=files, target_chars=350)

    assert len(bodies) == 1
    body = bodies[0]
    assert "around 350 characters" in body["instructions"]
    assert "complete sentence" in body["instructions"]
    assert "Use only the text in that file's chunks" in body["instructions"]
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"] == FILE_SUMMARY_SCHEMA
    assert body["model"] == "gpt-5-nano" and body["reasoning"] == {"effort": "minimal"}
    sent = json.loads(body["input"])
    assert sent["question"] == QUESTION
    assert [item["file"] for item in sent["files"]] == [1, 2, 3]
    assert sent["files"][1]["chunks"] == [PROFILE_CHUNK, PROFILE_SECOND_CHUNK]
    assert summaries == {
        2: "Currículo de engenheiro de software focado em Python e IA.",
        1: "Título de um texto sobre a gravidade do pecado de impureza.",
    }


def test_catalog_summaries_come_from_one_batched_call_over_each_files_chunks(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    scope, user, folder = _folder_with_files(session)
    provider = BriefProvider({
        1: "O arquivo traz apenas o título sobre a gravidade do pecado de impureza.",
        2: (
            "Perfil profissional de um engenheiro de software com cinco anos de experiência em Python, "
            "Django e FastAPI, com foco recente em soluções de IA generativa."
        ),
    })

    result, _tool_results, _references = _ask(
        session, provider, folder, scope, user, FileSummaries(target_chars=320, model="cheap"),
    )

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["target_chars"] == 320 and call["model"] == "cheap" and call["question"] == QUESTION
    assert [item["name"] for item in call["files"]] == ["A Gravidade.pdf", "Profile.pdf"]
    assert call["files"][1]["chunks"] == [PROFILE_CHUNK, PROFILE_SECOND_CHUNK]
    assert _row(result.answer, "A Gravidade.pdf") == (
        "- A Gravidade.pdf: O arquivo traz apenas o título sobre a gravidade do pecado de impureza."
    )
    assert _row(result.answer, "Profile.pdf").endswith("IA generativa.")
    assert "Síntese extrativa" not in result.answer
    assert "Key Strengths" not in result.answer
    assert _row(result.answer, "Vazio.pdf") == (
        "- Vazio.pdf: não há conteúdo indexado suficiente para resumir este arquivo."
    )
    # The Fontes block still carries a link per indexed file.
    assert {item.document_name for item in result.citations} == {"A Gravidade.pdf", "Profile.pdf", "Vazio.pdf"}
    assert all(item.source_url for item in result.citations)


def test_llm_failure_falls_back_to_leading_text_ended_at_a_sentence(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    scope, user, folder = _folder_with_files(session)
    provider = BriefProvider(AIProviderUnavailable("AI provider is unavailable"))

    result, _tool_results, _references = _ask(session, provider, folder, scope, user)

    assert len(provider.calls) == 1
    profile = _row(result.answer, "Profile.pdf")
    assert profile.startswith("- Profile.pdf: Síntese extrativa do conteúdo indexado: Contact")
    assert profile.endswith("Django and FastAPI.")
    assert "Key Strengths" not in profile and "Page 1 of 5" not in profile
    assert _row(result.answer, "A Gravidade.pdf").endswith(GRAVIDADE_CHUNK)
    assert all(item.source_url for item in result.citations)


def test_timeout_is_bounded_and_falls_back_without_inventing(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    scope, user, folder = _folder_with_files(session)
    provider = BriefProvider(AIProviderUnavailable("AI provider deadline exceeded"))

    before = time.monotonic()
    result, _tool_results, _references = _ask(
        session, provider, folder, scope, user, FileSummaries(timeout_seconds=0.5),
    )

    assert provider.calls[0]["deadline"] is not None
    assert provider.calls[0]["deadline"] <= before + 0.5 + 1.0
    assert "Síntese extrativa do conteúdo indexado:" in _row(result.answer, "Profile.pdf")
    assert _row(result.answer, "Vazio.pdf").endswith("não há conteúdo indexado suficiente para resumir este arquivo.")


def test_unfinished_or_missing_llm_summary_never_shows_a_cut_sentence(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    scope, user, folder = _folder_with_files(session)
    provider = BriefProvider({
        1: "",
        2: "Currículo de engenheiro de software. Trabalhou com Python, Django e",
    })

    result, _tool_results, _references = _ask(session, provider, folder, scope, user)

    assert _row(result.answer, "Profile.pdf") == "- Profile.pdf: Currículo de engenheiro de software."
    assert _row(result.answer, "A Gravidade.pdf") == (
        f"- A Gravidade.pdf: Síntese extrativa do conteúdo indexado: {GRAVIDADE_CHUNK}"
    )


def test_provider_without_batch_summaries_uses_the_sentence_fallback(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    scope, user, folder = _folder_with_files(session)

    result, _tool_results, _references = _ask(session, InventoryClassifier({}), folder, scope, user)

    assert _row(result.answer, "Profile.pdf").endswith("Django and FastAPI.")


def test_sentence_preview_never_cuts_inside_a_word() -> None:
    preview = _sentence_preview(PROFILE_CHUNK, 350)
    assert preview.endswith("Django and FastAPI.")
    assert len(preview) < 700

    no_sentence = _sentence_preview("palavra " * 100, 50)
    assert no_sentence.endswith("palavra…") and len(no_sentence) <= 51

    assert _sentence_preview("Curto.", 350) == "Curto."
    assert _complete_summary("sem ponto final", 350) == ""
    assert _complete_summary("  Frase um.\n Frase dois  ", 350) == "Frase um."


def test_catalog_row_without_summary_is_sentence_bounded_not_a_wall() -> None:
    excerpt = "Contact me\n\n" + "Key Strengths: - AI & Innovation: building systems. " * 30
    row = _catalog_item_row({"name": "Profile.pdf", "kind": "file", "excerpt": excerpt})

    assert row.startswith("- Profile.pdf: Síntese extrativa do conteúdo indexado: Contact me Key")
    assert "\n" not in row and row.endswith("building systems.")
    assert len(row) < 450
