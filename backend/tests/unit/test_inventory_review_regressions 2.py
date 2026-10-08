"""Regressions for the four independent-review findings (h-gw)."""
# ruff: noqa: F811
import unicodedata

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.knowledge.models import Document, DocumentChunk
from app.library.models import LibraryNode
from app.library.service import SNAPSHOT_MAX_CHUNK_CHARS, SNAPSHOT_MAX_CHUNKS, LibraryService
from tests.unit.test_inventory_followups import add_file, setup, turn
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


def snapshots(session, case, ids):
    return LibraryService(session).catalog_file_snapshots(
        scope=case[0], user_id=case[1].id, providers=["google_drive"], node_ids=ids,
    )


def override_assessments(monkeypatch, case, quote, *, matches=True):
    def analyze(**kwargs):
        return {
            index: {"matches": matches, "topic": "Carreira profissional", "evidence": quote}
            for index, _item in enumerate(kwargs["files"], 1)
        }
    monkeypatch.setattr(case[4], "analyze_file_topics", analyze)


def test_snapshot_sql_limits_rows_per_document_before_python(semantic_session, monkeypatch):
    case = setup(semantic_session)
    doc = semantic_session.scalar(select(Document).where(Document.name == "Profile.pdf"))
    for position in range(1, 40):
        semantic_session.add(DocumentChunk(
            organization_id=doc.organization_id, workspace_folder_id=doc.workspace_folder_id,
            document_id=doc.id, position=position,
            text=f"Passagem {position} do arquivo.", search_text="snapshot fixture",
        ))
    semantic_session.commit()
    execute = semantic_session.execute
    reads, statements = [], []

    def record(statement, *args, **kwargs):
        result = execute(statement, *args, **kwargs)
        sql = str(statement)
        if "document_chunks.text" in sql and "documents.external_file_id" in sql:
            rows = list(result)
            reads.append(len(rows))
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return rows
        return result

    monkeypatch.setattr(semantic_session, "execute", record)
    ids = list(semantic_session.scalars(select(LibraryNode.id).where(LibraryNode.kind == "file")))
    result = snapshots(semantic_session, case, ids)
    assert reads and sum(reads) <= SNAPSHOT_MAX_CHUNKS + 1
    assert len(next(item for item in result if item.id == case[3].id).chunks) == SNAPSHOT_MAX_CHUNKS
    assert next(item for item in result if item.name == "Indexed.pdf").chunks
    assert sum(item.index_status == "not_indexed" for item in result) == 1
    assert statements and "row_number() OVER (PARTITION BY" in statements[0]


def test_snapshot_caps_an_oversized_first_chunk(semantic_session):
    case = setup(semantic_session)
    doc = semantic_session.scalar(select(Document).where(Document.name == "Profile.pdf"))
    first = semantic_session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    first.text = "Software Engineer " * 1000
    semantic_session.commit()
    result = snapshots(semantic_session, case, [case[3].id])[0]
    assert sum(map(len, result.chunks)) <= SNAPSHOT_MAX_CHUNK_CHARS
    assert len(result.excerpt) <= SNAPSHOT_MAX_CHUNK_CHARS


@pytest.mark.parametrize("quote", [
    "a", "de", "Software Engineer", "... ... ... ... ... ...",
    pytest.param("x" * 1000, id="oversized-token"),
])
@pytest.mark.parametrize("matches", [True, False])
def test_weak_evidence_is_unknown_even_for_negative_assessment(semantic_session, monkeypatch, quote, matches):
    case = setup(semantic_session)
    doc = semantic_session.scalar(select(Document).where(Document.name == "Profile.pdf"))
    first = semantic_session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    first.text += " a de ... ... ... ... ... ... " + "x" * 1000
    semantic_session.commit()
    override_assessments(monkeypatch, case, quote, matches=matches)
    result, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic", target="library")
    assert refs == [] and result.citations == []
    assert result.resolved_context["topic_evaluated"] == 0
    assert result.resolved_context["topic_unknown"] == 3
    assert "Não foi possível avaliar" in result.answer


def test_evidence_normalizes_unicode_case_and_whitespace(semantic_session, monkeypatch):
    case = setup(semantic_session)
    quote = unicodedata.normalize("NFD", "SOFTWARE\tENGINEER COM EXPERIÊNCIA EM PYTHON.")
    override_assessments(monkeypatch, case, quote)
    result, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic", target="library")
    assert [ref["name"] for ref in refs] == ["Profile.pdf"]
    assert len(result.citations) == 1
    assert result.resolved_context["topic_evaluated"] == 1
    assert unicodedata.normalize("NFKC", result.citations[0].excerpt).casefold() == (
        "software engineer com experiência em python."
    )


def test_long_quote_from_another_file_is_not_accepted(semantic_session, monkeypatch):
    case = setup(semantic_session)
    override_assessments(monkeypatch, case, "O currículo apresenta experiência em gestão de produtos.")
    result, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic", target="library")
    assert refs == [] and result.citations == []
    assert result.resolved_context["topic_evaluated"] == 0


@pytest.mark.parametrize("followup", [False, True])
def test_folder_count_discloses_direct_children_and_keeps_scope(semantic_session, followup):
    case = setup(semantic_session)
    child = LibraryNode(
        organization_id=case[0].organization_id, source_id=case[2].source_id,
        parent_id=case[2].id, external_id="nested-folder", kind="folder", name="Subpasta",
    )
    semantic_session.add(child)
    semantic_session.flush()
    nested = LibraryNode(
        organization_id=case[0].organization_id, source_id=case[2].source_id,
        parent_id=child.id, external_id="nested-file", kind="file", name="Nested.pdf",
    )
    semantic_session.add(nested)
    semantic_session.commit()
    if followup:
        turn(semantic_session, case, "Liste", "list_files", mentions=[("folder", case[2].id)])
    mentions = () if followup else [("folder", case[2].id)]
    result, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", mentions=mentions)
    assert "São 3 arquivos" in result.answer
    assert len(refs) == 3 and all(ref["id"] != str(nested.id) for ref in refs)
    assert "arquivos diretamente" in result.answer
    assert "não inclui subpastas" in result.answer
    if followup:
        again, _, _ = turn(semantic_session, case, "Quantos mesmo?", "inventory_stats")
        assert "não inclui subpastas" in again.answer


def test_library_count_does_not_claim_a_direct_children_scope(semantic_session):
    case = setup(semantic_session)
    result, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", target="library")
    assert len(refs) == 3
    assert "não inclui subpastas" not in result.answer


def test_explicit_library_count_resets_previous_folder_scope(semantic_session):
    case = setup(semantic_session)
    turn(semantic_session, case, "Liste", "list_files", mentions=[("folder", case[2].id)])
    result, _, refs = turn(semantic_session, case, "Quantos na biblioteca?", "inventory_stats", target="library")
    assert len(refs) == 3
    assert "não inclui subpastas" not in result.answer


@pytest.mark.parametrize("empty", [False, True])
def test_folder_scope_survives_multiple_or_empty_folder_count(semantic_session, empty):
    case = setup(semantic_session)
    folder = LibraryNode(
        organization_id=case[0].organization_id, source_id=case[2].source_id,
        parent_id=case[2].id, external_id="empty-folder", kind="folder", name="Vazia",
    )
    semantic_session.add(folder)
    semantic_session.commit()
    mentions = [("folder", folder.id)]
    if not empty:
        mentions.append(("folder", case[2].id))
    first, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", mentions=mentions)
    assert len(refs) == (0 if empty else 3)
    assert "não inclui subpastas" in first.answer
    result, _, refs = turn(semantic_session, case, "Quantos mesmo?", "inventory_stats")
    assert len(refs) == (0 if empty else 3)
    assert "não inclui subpastas" in result.answer


def test_count_with_no_topics_omits_irrelevant_citations_keeps_references(semantic_session):
    case = setup(semantic_session)
    for index in range(28):
        add_file(semantic_session, case, f"Documento {index}.pdf", "O plano prioriza clientes existentes.")
    case[4].analysis_error = True
    result, _, refs = turn(semantic_session, case, "Quantos?", "inventory_stats", target="library")
    assert "São 31 arquivos" in result.answer and len(refs) == 31
    assert "temas de 31 arquivo(s)" in result.answer
    assert result.citations == []
    assert "fontes " not in result.answer
    case[4].analysis_error = False
    selected, _, refs = turn(semantic_session, case, "Quais falam de carreira?", "select_files_by_topic")
    assert [ref["name"] for ref in refs] == ["Profile.pdf"]
    assert len(selected.citations) == 1
