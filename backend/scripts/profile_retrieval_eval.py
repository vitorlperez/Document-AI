"""Real indexed retrieval, real (optionally cached) embeddings, captured synthesis.

Run through docker compose exec; requires an active member and an indexed Profile.pdf.
Usage writes are rolled back. No ingestion, source writes or running-service changes.
Metrics score original chunk positions, including members of merged passages, and
separately the facts actually visible to synthesis (a retrieved but cut chunk is
not usable evidence). --replay also calls the real answer model for every case.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.scoping import OrganizationScope
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import GeneratedAnswer, OpenAIQuestionProvider, QuestionService
from app.organizations.models import Membership


class CaptureProvider:
    def __init__(self, delegate, cache, replay):
        self.delegate, self.cache, self.replay = delegate, cache, replay
        self.evidence = []
        self.evidence_context_chars = getattr(delegate, "evidence_context_chars", 64000)

    def embed(self, *, texts):
        missing = [text for text in texts if text not in self.cache]
        if missing:
            self.cache.update(zip(missing, self.delegate.embed(texts=missing), strict=True))
        return [self.cache[text] for text in texts]

    def answer(self, *, question, evidence):
        self.evidence = evidence
        if self.replay:
            return self.delegate.answer(question=question, evidence=evidence)
        return GeneratedAnswer("Captured evidence [1].", list(range(1, len(evidence) + 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-cache", type=Path, required=True)
    parser.add_argument("--document-id", type=UUID)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    delegate = OpenAIQuestionProvider(
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    )
    if hasattr(settings, "evidence_context_chars"):
        delegate.evidence_context_chars = settings.evidence_context_chars
    cache = json.loads(args.embedding_cache.read_text()) if args.embedding_cache.exists() else {}
    cases = json.loads(args.cases.read_text())
    report = {"mode": "real_llm" if args.replay else "captured_synthesis", "cases": []}
    with Session(build_engine(settings)) as session:
        query = select(Document).where(Document.name == "Profile.pdf", Document.index_status == "indexed")
        if args.document_id:
            query = query.where(Document.id == args.document_id)
        documents = session.scalars(query).all()
        if len(documents) != 1:
            raise SystemExit("Specify --document-id: expected exactly one indexed Profile.pdf")
        document = documents[0]
        member = session.scalars(select(Membership).where(
            Membership.organization_id == document.organization_id, Membership.is_active.is_(True)
        ).order_by(Membership.user_id)).first()
        if member is None:
            raise SystemExit("No active member for the indexed document")
        chunks = session.scalars(select(DocumentChunk).where(
            DocumentChunk.document_id == document.id
        ).order_by(DocumentChunk.position)).all()
        positions = {chunk.id: chunk.position for chunk in chunks}
        report["document_id"] = str(document.id)
        report["chunk_lengths"] = {chunk.position: len(chunk.text) for chunk in chunks}
        organization_id, user_id, folder_id, document_id = (
            document.organization_id, member.user_id, document.workspace_folder_id, document.id
        )
        for case in cases:
            provider = CaptureProvider(delegate, cache, args.replay)
            result = QuestionService(session, provider).ask(
                scope=OrganizationScope(organization_id), user_id=user_id,
                workspace_folder_id=folder_id, document_ids={document_id},
                question=case["question"], answer_mode="relevance",
            )
            selected = {positions[chunk_id] for item in provider.evidence
                        for chunk_id in (getattr(item, "chunk_ids", ()) or (item.chunk_id,))}
            expected = set(case["expected_positions"])
            hits = len(expected & selected)
            text = "\n".join(item.excerpt for item in provider.evidence)
            facts = [fact for fact in case["facts"] if fact in text]
            report["cases"].append({
                "id": case["id"], "question": case["question"],
                "expected": sorted(expected), "selected": sorted(selected), "hits": hits,
                "recall": hits / len(expected), "precision": hits / len(selected) if selected else 0,
                "visible_facts": len(facts), "expected_facts": len(case["facts"]),
                "context_chars": len(text), "passages": len(provider.evidence),
                "linked_citations": sum(bool(item.source_url) for item in result.citations),
                "answer": result.answer if args.replay else None,
                "retrieval_status": result.retrieval_status,
            })
            session.rollback()
    runs = report["cases"]
    hits = sum(run["hits"] for run in runs)
    expected = sum(len(run["expected"]) for run in runs)
    selected = sum(len(run["selected"]) for run in runs)
    report["micro"] = {
        "hits": hits, "expected": expected, "selected": selected,
        "recall": hits / expected, "precision": hits / selected if selected else 0,
        "visible_facts": sum(run["visible_facts"] for run in runs),
        "expected_facts": sum(run["expected_facts"] for run in runs),
    }
    args.embedding_cache.write_text(json.dumps(cache))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
