"""Gaps and quality panel for owners/admins.

Aggregates counts and authorised metadata only (retrieval status, assessment outcome, feedback
vote, document failure codes). Conversation text, questions and answers are never read out.
"""
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.api.usage import require_org_admin
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Conversation, ConversationMessage, Document
from app.workspaces.models import WorkspaceFolder

router = APIRouter(tags=["insights"])
GAP_STATUSES = ("no_indexed_content", "below_evidence_threshold", "no_compatible_embeddings")
MESSAGE_SCAN_LIMIT = 5000


def answer_stats(session: Session, organization_id: UUID, since: datetime) -> dict[str, object]:
    rows = session.execute(
        select(ConversationMessage.context, ConversationMessage.response)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(Conversation.organization_id == organization_id, ConversationMessage.role == "assistant",
               ConversationMessage.created_at >= since)
        .order_by(ConversationMessage.created_at.desc()).limit(MESSAGE_SCAN_LIMIT)
    ).all()
    statuses: Counter[str] = Counter()
    assessments: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    votes: Counter[str] = Counter()
    gap_by_provider: Counter[str] = Counter()
    for context, response in rows:
        context = context or {}
        status = str((response or {}).get("retrieval_status") or "unknown")
        statuses[status] += 1
        resolved = context.get("resolved_context") or {}
        outcome = (resolved.get("assessment") or {}).get("outcome")
        if outcome:
            assessments[str(outcome)] += 1
        vote = (context.get("feedback") or {}).get("vote")
        if vote in ("up", "down"):
            votes[vote] += 1
        for provider in resolved.get("providers") or []:
            providers[str(provider)] += 1
            if status in GAP_STATUSES:
                gap_by_provider[str(provider)] += 1
    gaps = sum(statuses[s] for s in GAP_STATUSES)
    return {
        "total_answers": len(rows), "truncated": len(rows) >= MESSAGE_SCAN_LIMIT,
        "retrieval_status": dict(statuses), "assessment": dict(assessments),
        "feedback": {"up": votes["up"], "down": votes["down"]},
        "gap_answers": gaps, "gap_ratio": round(gaps / len(rows), 4) if rows else 0.0,
        "by_provider": [{"provider": p, "answers": n, "gap_answers": gap_by_provider[p]}
                        for p, n in providers.most_common()],
    }


def folder_health(session: Session, organization_id: UUID) -> list[dict[str, object]]:
    folders = session.execute(
        select(WorkspaceFolder, DataSource.provider)
        .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
        .where(WorkspaceFolder.organization_id == organization_id).order_by(WorkspaceFolder.name, WorkspaceFolder.id)
    ).all()
    counts: dict[UUID, Counter[str]] = {}
    errors: dict[UUID, Counter[str]] = {}
    for folder_id, status, code, total in session.execute(
        select(Document.workspace_folder_id, Document.index_status, Document.error_code, func.count())
        .where(Document.organization_id == organization_id)
        .group_by(Document.workspace_folder_id, Document.index_status, Document.error_code)
    ):
        counts.setdefault(folder_id, Counter())[status] += total
        if status == "failed":
            errors.setdefault(folder_id, Counter())[code or "unknown"] += total
    result = []
    for folder, provider in folders:
        by_status = counts.get(folder.id, Counter())
        failed = by_status["failed"]
        actions = []
        if failed:
            actions.append({"kind": "reprocess", "workspace_id": str(folder.id)})
        if not by_status["indexed"]:
            actions.append({"kind": "connect_folder", "workspace_id": str(folder.id)})
        result.append({
            "workspace_id": str(folder.id), "name": folder.name, "provider": provider, "status": folder.status,
            "last_synced_at": folder.last_synced_at, "indexed": by_status["indexed"], "failed": failed,
            "skipped": by_status["skipped"], "error_codes": dict(errors.get(folder.id, {})), "actions": actions,
        })
    return result


@router.get("/organizations/{organization_id}/insights")
def organization_insights(organization_id: UUID, days: int = Query(30, ge=1, le=180),
                          user: User = Depends(current_user),
                          session: Session = Depends(database_session)) -> dict[str, object]:
    require_org_admin(session, organization_id, user.id)
    since = datetime.now(UTC) - timedelta(days=days)
    answers = answer_stats(session, organization_id, since)
    folders = folder_health(session, organization_id)
    suggestions = []
    if answers["total_answers"] and answers["gap_ratio"] >= 0.2:
        suggestions.append({"kind": "connect_folder", "reason": "many_unanswered"})
    for folder in folders:
        if folder["failed"]:
            suggestions.append({"kind": "reprocess", "workspace_id": folder["workspace_id"], "name": folder["name"],
                                "reason": "failed_documents", "count": folder["failed"]})
    if not folders:
        suggestions.append({"kind": "connect_folder", "reason": "no_folders"})
    return {"days": days, "answers": answers, "folders": folders, "suggestions": suggestions}
