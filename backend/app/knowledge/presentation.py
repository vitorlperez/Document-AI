"""Shared response presentation and output-link guard."""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.questions import QuestionResult

MAX_CITATION_EXCERPT_LENGTH = 240
_MARKDOWN_LINK_START = re.compile(r"\[([^\]]+)\]\(")
_AUTOLINK = re.compile(r"<\s*(?:https?://|www\.)[^>]+>", re.IGNORECASE)
_URL = re.compile(
    r"\b(?:(?:https?://|www\.)[^\s<>]+|(?:drive|docs)\.google\.com/[^\s<>]+|"
    r"(?:[A-Za-z0-9-]+\.)?notion\.(?:so|site)/[^\s<>]+)",
    re.IGNORECASE,
)
_SOURCE_LINK_LINE = re.compile(
    r"\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|\[\d+\]:)"
    r"[^\n]*(?:https?://|www\.|(?:drive|docs)\.google\.com/|notion\.(?:so|site)/)[^\n]*",
    re.IGNORECASE,
)
_SOURCE_ONLY_LINE = re.compile(
    r"\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|\[\d+\]:)\s*[.,;:!?()\[\]\s]*",
    re.IGNORECASE,
)
_PROVIDER_URL = re.compile(
    r"\s*\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*(?:https?://|www\.)[^)\n]*\)",
    re.IGNORECASE,
)
_INLINE_CITATION_MARKER = re.compile(r"\[\d+\]")


def serialize_question_result(
    result: "QuestionResult", *, include_provider: bool
) -> dict[str, object]:
    citations = []
    for item in result.citations:
        citation = {
            "document_id": str(item.document_id),
            "document_name": item.document_name,
            "excerpt": short_citation_excerpt(item.excerpt),
            "page_number": item.page_number,
            "source_url": item.source_url,
        }
        if include_provider and item.source_provider:
            citation["source_provider"] = item.source_provider
        citations.append(citation)
    payload: dict[str, object] = {
        "answer": answer_without_source_links(result.answer),
        "confidence": result.confidence,
        "citations": citations,
        "retrieval_status": result.retrieval_status,
    }
    if result.coverage is not None:
        payload["coverage"] = result.coverage
    if result.resolved_context is not None:
        payload["resolved_context"] = result.resolved_context
    return payload


def short_citation_excerpt(value: str) -> str:
    """Keep displayed quotes concise without shortening evidence sent to the model."""
    excerpt = value.strip()
    if len(excerpt) <= MAX_CITATION_EXCERPT_LENGTH:
        return excerpt
    cutoff = max(
        excerpt.rfind(separator, 0, MAX_CITATION_EXCERPT_LENGTH) for separator in (" ", "\n", "\t")
    )
    if cutoff < MAX_CITATION_EXCERPT_LENGTH * 0.65:
        cutoff = MAX_CITATION_EXCERPT_LENGTH - 1
    return f"{excerpt[:cutoff].rstrip()}…"


def answer_without_source_links(value: str | None) -> str | None:
    """Strip accidental model-generated URLs; source links belong to citations."""
    if value is None:
        return None
    answer = "\n".join(line for line in value.splitlines() if not _SOURCE_LINK_LINE.fullmatch(line))
    answer, _ = strip_answer_links(answer)
    # Current answers carry validated "fonte N" labels. Raw markers from older
    # providers are still discarded; never guess a document from an unknown index.
    answer = _INLINE_CITATION_MARKER.sub("", answer)
    answer = re.sub(r"\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*\)", "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"\(\s*\)", "", answer)
    answer = re.sub(r"[ \t]+([,.;:!?])", r"\1", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = "\n".join(
        line for line in answer.splitlines() if not _SOURCE_ONLY_LINE.fullmatch(line)
    )
    # ":::" closes a presentation block (see ANSWER_FORMAT_GUIDANCE); keep it.
    answer = re.sub(r"(?m)^\s*(?!:::\s*$)[.,;:!?]+\s*$", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


def _strip_markdown_links(value: str, *, counter: list[int] | None = None) -> str:
    """Retain link labels while consuming balanced URL parentheses."""
    parts: list[str] = []
    cursor = 0
    for match in _MARKDOWN_LINK_START.finditer(value):
        if match.start() < cursor:
            continue
        depth = 1
        end = match.end()
        while end < len(value) and depth:
            if value[end] == "(":
                depth += 1
            elif value[end] == ")":
                depth -= 1
            end += 1
        if depth:
            continue
        if counter is not None:
            counter[0] += 1
        start = match.start()
        image = start > 0 and value[start - 1] == "!"
        parts.extend(
            (value[cursor : start - 1 if image else start], "" if image else match.group(1))
        )
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts)


def _remove_url_preserving_punctuation(match: re.Match[str]) -> str:
    url = match.group()
    suffix = ""
    while url and url[-1] in ".,;:!?":
        suffix = url[-1] + suffix
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        suffix = ")" + suffix
        url = url[:-1]
    return suffix


def strip_answer_links(value: str) -> tuple[str, int]:
    """Guard service output without changing citation markers before validation."""
    counter = [0]
    stripped = _strip_markdown_links(value, counter=counter)
    count = counter[0]
    for pattern, replacement in (
        (_AUTOLINK, ""),
        (_PROVIDER_URL, ""),
        (_URL, _remove_url_preserving_punctuation),
    ):
        stripped, removed = pattern.subn(replacement, stripped)
        count += removed
    if count:
        logging.getLogger(__name__).info(
            "answer_links_stripped", extra={"event": "answer_links_stripped", "count": count}
        )
    return stripped, count
