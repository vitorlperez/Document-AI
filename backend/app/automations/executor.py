"""Run one automation with its creator's permissions and deliver the cited result."""
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_usage.service import UsageLimitExceeded
from app.automations.models import Automation, AutomationRun
from app.automations.triggers import scope_folder_ids
from app.automations.webhooks import enqueue_completed
from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable, QuestionService, SemanticProvider
from app.library.service import LibraryService
from app.notifications.followed import BODY_CHARS, citation_payload
from app.notifications.service import NotificationService
from app.organizations.delivery import EmailDeliveryPort

logger = logging.getLogger(__name__)
TEMPLATE_HINTS = {
    "table": " Responda com uma tabela Markdown.",
    "alert": " Responda apenas com o que exige atenção; se não houver nada relevante, diga que não há.",
}
MAX_QUESTION_CHARS = 1000


def build_question(automation: Automation) -> str:
    prompt = " ".join(automation.prompt.split())
    hint = TEMPLATE_HINTS.get(automation.template, "")
    return prompt + hint if len(prompt) + len(hint) <= MAX_QUESTION_CHARS else prompt


def pdf_path(automation: Automation, run: AutomationRun) -> str:
    return f"/organizations/{automation.organization_id}/automations/{automation.id}/runs/{run.id}/pdf"


def accessible_folders(session: Session, scope: OrganizationScope, user_id: UUID) -> set[UUID] | None:
    """Folders a member may ask about (the library is the authority); ``None`` when not an active member."""
    try:
        return {item.id for item in LibraryService(session).question_contexts(scope=scope, user_id=user_id)}
    except SyncAccessDenied:
        return None


def _finish(run: AutomationRun, status: str, *, error_code: str | None = None, result: dict[str, object] | None = None) -> None:
    run.status = status
    run.error_code = error_code
    run.result = result
    run.finished_at = datetime.now(UTC)


def _notify_creator(session: Session, automation: Automation, run: AutomationRun, *, kind: str, title: str, body: str,
                    extra: dict[str, object], email: EmailDeliveryPort | None, app_url: str) -> None:
    NotificationService(session).notify(
        scope=OrganizationScope(automation.organization_id), user_id=automation.created_by_user_id, kind=kind,
        title=title, body=body, data={"automation_id": str(automation.id), "run_id": str(run.id), **extra},
        email=email, app_url=app_url)


def execute_run(session: Session, run_id: UUID, *, provider: SemanticProvider | None, email: EmailDeliveryPort | None = None,
                app_url: str = "", send_task: Callable[..., object] | None = None) -> str | None:
    """Claim and execute a queued run; returns its final status (``None`` when it was not claimable)."""
    run = session.scalar(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update())
    if run is None or run.status != "queued":
        return None  # already claimed or finished: task re-delivery is a no-op
    automation = session.get(Automation, run.automation_id)
    if automation is None:
        return None
    run.status = "running"
    run.started_at = datetime.now(UTC)
    session.commit()

    scope = OrganizationScope(automation.organization_id)
    creator = automation.created_by_user_id
    folder_ids = scope_folder_ids(automation)
    failure_email = None  # failures and quota warnings go to the creator's bell; e-mail only for results
    if provider is None:
        _finish(run, "error", error_code="ai_unavailable")
    else:
        allowed = accessible_folders(session, scope, creator)
        if allowed is None or not folder_ids or not set(folder_ids) <= allowed:
            _finish(run, "error", error_code="creator_access_lost")
        else:
            run.documents_considered = session.scalar(select(func.count(Document.id)).where(
                Document.organization_id == automation.organization_id, Document.workspace_folder_id.in_(folder_ids),
                Document.index_status == "indexed")) or 0
            try:
                with session.begin_nested():
                    result = QuestionService(session, provider).ask(
                        scope=scope, user_id=creator, workspace_folder_ids=folder_ids, question=build_question(automation),
                        answer_mode="summary" if automation.template == "summary" else None)
                run.questions_used = 1
            except UsageLimitExceeded:
                _finish(run, "quota")
            except AIProviderUnavailable:
                _finish(run, "error", error_code="ai_unavailable")
            except GoogleAccessDenied:
                _finish(run, "error", error_code="creator_access_lost")
            except ValueError:
                _finish(run, "error", error_code="scope_unavailable")
            except Exception:
                logger.exception("automation run failed")
                _finish(run, "error", error_code="internal_error")
            else:
                _deliver(session, automation, run, result, scope=scope, allowed=allowed, folder_ids=folder_ids,
                         email=email, app_url=app_url)

    if run.status == "quota":
        _notify_creator(session, automation, run, kind="automation_quota", title=f"“{automation.name}” não rodou: cota mensal esgotada",
                        body="A cota mensal de perguntas da organização acabou. A automação volta a rodar quando a cota renovar ou o plano mudar.",
                        extra={}, email=failure_email, app_url=app_url)
    elif run.status == "error":
        _notify_creator(session, automation, run, kind="automation_failed", title=f"“{automation.name}” falhou",
                        body="Não foi possível concluir esta execução. Tente executar de novo.",
                        extra={"error_code": run.error_code}, email=failure_email, app_url=app_url)
    session.commit()
    enqueue_completed(session, automation, run, send_task)  # outbound webhooks; never fails the run
    return run.status


def _deliver(session: Session, automation: Automation, run: AutomationRun, result, *, scope: OrganizationScope,
             allowed: set[UUID], folder_ids: list[UUID], email: EmailDeliveryPort | None, app_url: str) -> None:
    automation.last_run_at = datetime.now(UTC)
    citations = citation_payload(result.citations)
    if result.answer is None:
        _finish(run, "empty", result={"answer": None, "citations": [], "skipped_recipients": [], "notified": 0})
        return
    recipients = list(dict.fromkeys([str(automation.created_by_user_id), *[str(item) for item in automation.recipients or []]]))
    skipped: list[dict[str, str]] = []
    notified = 0
    wants = set(automation.output_formats or [])
    data: dict[str, object] = {"automation_id": str(automation.id), "run_id": str(run.id), "template": automation.template,
                               "citations": citations}
    if "pdf" in wants:
        data["pdf_path"] = pdf_path(automation, run)
    for raw in recipients:
        user_id = UUID(raw)
        folders = allowed if user_id == automation.created_by_user_id else accessible_folders(session, scope, user_id)
        if folders is None:
            skipped.append({"user_id": raw, "reason": "not_member"})
            continue
        if not set(folder_ids) <= folders:
            skipped.append({"user_id": raw, "reason": "no_folder_access"})
            continue
        NotificationService(session).notify(
            scope=scope, user_id=user_id, kind="automation_result", title=automation.name,
            body=result.answer[:BODY_CHARS], data=data, email=email if "email" in wants else None, app_url=app_url)
        notified += 1
    if skipped:
        logger.info("automation recipients skipped", extra={"automation_id": str(automation.id), "skipped": len(skipped)})
    _finish(run, "ok", result={"answer": result.answer, "citations": citations, "skipped_recipients": skipped,
                               "notified": notified})
