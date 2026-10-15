"""Deterministic overview card (themes, document types, suggested questions) for the selected scope.

Built only from the local catalog of indexed documents in folders the user can already query, so it costs no
model call or question quota and reveals nothing beyond what the member can see in the library. Results are
cached per scope and invalidated whenever the indexed set changes.
"""
import re
from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.models import Document
from app.library.service import LibraryService
from app.library.tool_groups import tool_group, tool_groups

_STOPWORDS = frozenset(
    ["a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "um", "uma", "para", "por", "com", "sem", "sobre", "the", "of", "and", "for", "to", "in", "on", "at", "final", "versao", "version", "v", "copia", "copy", "novo", "nova", "new", "rev", "draft", "rascunho", "doc", "docs", "documento", "arquivo", "file", "pdf", "docx", "xlsx", "pptx", "txt", "md"]
)
_TYPE_LABELS = (
    ("pdf", "PDF"), ("spreadsheet", "Planilhas"), ("excel", "Planilhas"), ("csv", "Planilhas"),
    ("presentation", "Apresentações"), ("powerpoint", "Apresentações"), ("word", "Documentos de texto"),
    ("document", "Documentos de texto"), ("text/", "Texto"), ("markdown", "Texto"), ("notion", "Páginas Notion"),
    ("clickup", "Tarefas ClickUp"), ("html", "Páginas web"), ("image", "Imagens"),
)
MAX_SUGGESTIONS = 5
_CACHE: dict[tuple, dict[str, object]] = {}
_CACHE_LIMIT = 256


def _type_label(mime_type: str) -> str:
    lowered = mime_type.lower()
    return next((label for needle, label in _TYPE_LABELS if needle in lowered), "Outros")


def _themes(names: Iterable[str], limit: int = 6) -> list[str]:
    counts: Counter[str] = Counter()
    for name in names:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
        words = [w for w in re.findall(r"[^\W\d_]{4,}", stem.lower()) if w not in _STOPWORDS]
        counts.update(set(words))
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word for word, _ in ranked[:limit]]


def _questions(themes: list[str], recent: list[str]) -> list[str]:
    questions = []
    if recent:
        questions.append(f"Faça um resumo de «{recent[0][:80]}».")
    for theme in themes[:3]:
        questions.append(f"Quais são os pontos principais sobre {theme}?")
    if len(themes) > 3:
        questions.append(f"Quais documentos falam de {themes[3]}?")
    questions.append("Quais foram os documentos atualizados mais recentemente?")
    if len(recent) > 1:
        questions.append(f"O que muda entre «{recent[0][:50]}» e «{recent[1][:50]}»?")
    return questions[:MAX_SUGGESTIONS]


def folder_overview(
    session: Session, *, scope: OrganizationScope, user_id: UUID, providers: list[str]
) -> dict[str, object]:
    """Overview for the member's queryable folders; ``providers`` empty means every tool."""
    contexts = LibraryService(session).question_contexts(scope=scope, user_id=user_id)
    wanted = tool_groups(providers)
    folder_ids = sorted(
        item.id for item in contexts
        if item.query_status in {"ready", "no_compatible_embeddings"} and (not wanted or tool_group(item.source_provider) in wanted)
    )
    empty: dict[str, object] = {"document_count": 0, "themes": [], "types": [], "suggested_questions": []}
    if not folder_ids:
        return empty
    where = (
        Document.organization_id == scope.organization_id,
        Document.workspace_folder_id.in_(folder_ids),
        Document.index_status == "indexed",
    )
    count, newest = session.execute(select(func.count(), func.max(Document.indexed_at)).where(*where)).one()
    if not count:
        return empty
    key = (scope.organization_id, tuple(folder_ids), int(count), newest)
    if key in _CACHE:
        return _CACHE[key]
    rows = session.execute(
        select(Document.name, Document.mime_type).where(*where)
        .order_by(Document.modified_at.desc().nulls_last(), Document.name).limit(500)
    ).all()
    types = Counter(_type_label(mime) for _, mime in rows)
    themes = _themes(name for name, _ in rows)
    card: dict[str, object] = {
        "document_count": int(count),
        "themes": themes,
        "types": [{"label": label, "count": n} for label, n in types.most_common(5)],
        "suggested_questions": _questions(themes, [name for name, _ in rows[:2]]),
    }
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = card
    return card
