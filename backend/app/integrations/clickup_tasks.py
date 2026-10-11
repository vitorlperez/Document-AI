"""Create a ClickUp task from a stored answer: a human-approved write (ADR-0020).

Never reachable from the agent, the MCP server or any model-driven tool. The caller is an authenticated
organization member acting on their own stored answer; the list must be one the admin selected for the
ClickUp source; every attempt is recorded in `clickup_task_creations` and audited.
"""
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.integrations.clickup import (
    LIST_PREFIX,
    ClickUpOAuthClient,
    ClickUpOutcomeUnknown,
    ClickUpRateLimited,
    ClickUpRemoteUnauthorized,
    ClickUpWriteRejected,
)
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable, SourceRemoteUnauthorized
from app.integrations.google_drive import GoogleOAuthUnavailable
from app.integrations.models import ClickUpTaskCreation, DataSource
from app.knowledge.models import ConversationMessage, Document
from app.knowledge.untrusted import sanitize_label, strip_invisible
from app.library.models import LibraryNode
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

logger = logging.getLogger("document_intelligence.integration")

MAX_NAME_CHARS = 200
MAX_DESCRIPTION_CHARS = 20_000
MAX_TAGS = 10
MAX_TAG_CHARS = 50
MAX_ASSIGNEES = 10
CREATIONS_PER_MINUTE = 5
SUGGESTED_TITLE_CHARS = 120
_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RAW_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DUE_MIN, _DUE_MAX = date(2000, 1, 1), date(2100, 12, 31)


class ClickUpTaskError(Exception):
    """A refusal with the HTTP status and the (pt-BR) message the interface shows."""

    def __init__(self, status: int, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


@dataclass(frozen=True)
class AvailableList:
    id: str  # raw ClickUp list id
    name: str
    path: str


@dataclass(frozen=True)
class TaskInput:
    list_id: str
    name: str
    description: str = ""
    assignees: tuple[int, ...] = ()
    due_date: date | None = None
    priority: int | None = None
    tags: tuple[str, ...] = ()


def authorship_footer(email: str) -> str:
    return f"Criada pelo Arquivio a pedido de {sanitize_label(email)}"


def _clean(text: str) -> str:
    return _CONTROL.sub("", strip_invisible(text)).replace("\r\n", "\n").replace("\r", "\n")


def clean_task_input(task: TaskInput) -> TaskInput:
    """Bound and sanitize the final fields (the interface lets the user edit everything)."""
    name = " ".join(_clean(task.name).split())[:MAX_NAME_CHARS]
    if not name:
        raise ClickUpTaskError(422, "Informe o título da tarefa.")
    if not _RAW_ID.match(task.list_id):
        raise ClickUpTaskError(422, "Lista inválida.")
    description = _clean(task.description).strip()[:MAX_DESCRIPTION_CHARS]
    tags = tuple(dict.fromkeys(tag for tag in (" ".join(_clean(tag).split())[:MAX_TAG_CHARS] for tag in task.tags) if tag))
    if len(tags) > MAX_TAGS:
        raise ClickUpTaskError(422, f"Use no máximo {MAX_TAGS} etiquetas.")
    assignees = tuple(dict.fromkeys(task.assignees))
    if len(assignees) > MAX_ASSIGNEES or any(not 0 < value < 2**53 for value in assignees):
        raise ClickUpTaskError(422, "Responsáveis inválidos.")
    if task.priority is not None and task.priority not in {1, 2, 3, 4}:
        raise ClickUpTaskError(422, "Prioridade inválida.")
    if task.due_date is not None and not _DUE_MIN <= task.due_date <= _DUE_MAX:
        raise ClickUpTaskError(422, "Prazo inválido.")
    return TaskInput(task.list_id, name, description, assignees, task.due_date, task.priority, tags)


def clickup_payload(task: TaskInput, *, footer: str) -> dict:
    """ClickUp "Create Task" body. The authorship footer is always added here, never trusted from the client."""
    body = f"{task.description}\n\n---\n_{footer}_" if task.description else f"_{footer}_"
    payload: dict = {"name": task.name, "markdown_content": body}
    if task.assignees:
        payload["assignees"] = list(task.assignees)
    if task.due_date is not None:  # noon UTC keeps the calendar day in every timezone
        moment = datetime(task.due_date.year, task.due_date.month, task.due_date.day, 12, tzinfo=UTC)
        payload["due_date"] = int(moment.timestamp() * 1000)
        payload["due_date_time"] = False
    if task.priority is not None:
        payload["priority"] = task.priority
    if task.tags:
        payload["tags"] = list(task.tags)
    return payload


def _url(value: object) -> str | None:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def suggested_title(question: str | None) -> str:
    line = next((item for item in _clean(question or "").splitlines() if item.strip()), "")
    title = " ".join(line.split())
    if len(title) > SUGGESTED_TITLE_CHARS:
        title = title[: SUGGESTED_TITLE_CHARS - 1].rstrip() + "…"
    return title or "Resposta do Arquivio"


def draft_description(answer: str, citations: list[dict]) -> str:
    """Answer text plus a "Fontes" section; the authorship footer is added on create, not here."""
    lines = []
    for item in citations:
        name = sanitize_label(item.get("document_name")) if isinstance(item.get("document_name"), str) else ""
        if not name:
            continue
        url = _url(item.get("source_url"))
        entry = f"[{name.replace('[', '(').replace(']', ')')}]({url.replace(')', '%29')})" if url else name
        if f"- {entry}" not in lines:
            lines.append(f"- {entry}")
    text = _clean(answer).strip()
    return f"{text}\n\n## Fontes\n" + "\n".join(lines) if lines else text


class ClickUpTaskService:
    def __init__(self, session: Session, client: ClickUpOAuthClient, cipher):
        self.session, self.client, self.cipher = session, client, cipher

    # --- source and lists (local data only: no ClickUp call decides visibility or the list menu) ---

    def source(self, organization_id: UUID) -> DataSource:
        source = self.session.scalar(select(DataSource).where(
            DataSource.organization_id == organization_id, DataSource.provider == "clickup",
        ).order_by(DataSource.created_at.desc(), DataSource.id.desc()))
        if source is None:
            raise ClickUpTaskError(404, "O ClickUp não está conectado a esta organização.")
        if source.status != "connected":
            raise ClickUpTaskError(409, "A conexão com o ClickUp precisa ser refeita por um administrador.")
        return source

    def _nodes(self, source: DataSource) -> dict[UUID, LibraryNode]:
        return {node.id: node for node in self.session.scalars(select(LibraryNode).where(
            LibraryNode.source_id == source.id, LibraryNode.organization_id == source.organization_id,
            LibraryNode.kind.in_(["folder", "source"])))}

    @staticmethod
    def _path(node: LibraryNode, nodes: dict[UUID, LibraryNode]) -> str:
        names, seen = [], set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            if node.kind != "source":
                names.append(node.name)
            node = nodes.get(node.parent_id) if node.parent_id else None
        return " > ".join(reversed(names))

    def selected_lists(self, source: DataSource) -> list[AvailableList]:
        """Lists the admin selected for the source (directly or through a Space/Folder/Workspace)."""
        selections = list(self.session.scalars(
            select(WorkspaceFolderSelection).join(
                WorkspaceFolder, WorkspaceFolder.id == WorkspaceFolderSelection.workspace_folder_id,
            ).where(WorkspaceFolder.source_id == source.id, WorkspaceFolder.organization_id == source.organization_id)))
        everything = any(item.kind == "all_accessible" for item in selections)
        chosen = {item.external_folder_id for item in selections if item.kind == "folder"}
        if not everything and not chosen:
            return []
        nodes = self._nodes(source)
        lists = []
        for node in nodes.values():
            if not node.external_id.startswith(LIST_PREFIX):
                continue
            ancestor, seen, allowed = node, set(), everything
            while not allowed and ancestor is not None and ancestor.id not in seen:
                seen.add(ancestor.id)
                allowed = ancestor.external_id in chosen
                ancestor = nodes.get(ancestor.parent_id) if ancestor.parent_id else None
            if allowed:
                lists.append(AvailableList(node.external_id.removeprefix(LIST_PREFIX), node.name, self._path(node, nodes)))
        return sorted(lists, key=lambda item: (item.path.lower(), item.id))

    def require_list(self, source: DataSource, list_id: str) -> AvailableList:
        found = next((item for item in self.selected_lists(source) if item.id == list_id), None)
        if found is None:
            raise ClickUpTaskError(422, "Escolha uma das listas do ClickUp liberadas pelo administrador.")
        return found

    def suggest_list(self, source: DataSource, lists: list[AvailableList], citations: list[dict]) -> str | None:
        """List of the ClickUp source most cited by the answer, else the first available one."""
        if not lists:
            return None
        document_ids = []
        for item in citations:
            try:
                document_ids.append(UUID(str(item.get("document_id"))))
            except ValueError:
                continue
        counts: Counter[str] = Counter()
        if document_ids:
            external_ids = list(self.session.scalars(select(Document.external_file_id).where(
                Document.id.in_(document_ids), Document.organization_id == source.organization_id)))
            nodes = self._nodes(source)
            files = self.session.scalars(select(LibraryNode).where(
                LibraryNode.source_id == source.id, LibraryNode.external_id.in_(external_ids)))
            for file in files:
                node, seen = file, set()
                while node is not None and node.id not in seen:
                    seen.add(node.id)
                    if node.external_id.startswith(LIST_PREFIX):
                        counts[node.external_id.removeprefix(LIST_PREFIX)] += 1
                        break
                    node = nodes.get(node.parent_id) if node.parent_id else None
        available = {item.id for item in lists}
        ranked = [(count, list_id) for list_id, count in counts.items() if list_id in available]
        return max(ranked, key=lambda pair: (pair[0], pair[1]))[1] if ranked else lists[0].id

    # --- remote reads for the form (explicit user action, one list at a time) ---

    def _credentials(self, source: DataSource) -> OAuthCredentials:
        try:
            return self.cipher.decrypt(source.encrypted_credentials or "")
        except GoogleOAuthUnavailable as error:
            raise ClickUpTaskError(503, "A integração com o ClickUp está indisponível no momento.") from error

    def _remote(self, source: DataSource, call):
        try:
            return call(self._credentials(source))
        except (ClickUpRemoteUnauthorized, SourceRemoteUnauthorized) as error:
            self._flag_reauth(source)
            raise ClickUpTaskError(409, "A conexão com o ClickUp expirou. Peça a um administrador para reconectar.") from error
        except SourceItemUnavailable as error:
            raise ClickUpTaskError(403, "Sem permissão para esta lista no ClickUp.") from error

    def _flag_reauth(self, source: DataSource) -> None:
        source.status = "reauth_required"
        self.session.commit()

    def list_options(self, source: DataSource, list_id: str) -> dict:
        self.require_list(source, list_id)
        members = self._remote(source, lambda credentials: self.client.list_members(credentials=credentials, list_id=list_id))
        statuses = self._remote(source, lambda credentials: self.client.list_statuses(credentials=credentials, list_id=list_id))
        return {
            "list_id": list_id,
            "members": [
                {"id": int(member["id"]), "name": sanitize_label(str(member.get("username") or member.get("email") or "")),
                 "email": member.get("email") if isinstance(member.get("email"), str) else None}
                for member in members if str(member.get("id", "")).isdigit()
            ],
            "statuses": [sanitize_label(str(status["status"])) for status in statuses if status.get("status")],
        }

    # --- create ---

    def _rate_limit(self, user_id: UUID) -> None:
        since = datetime.now(UTC) - timedelta(minutes=1)
        recent = self.session.scalar(select(func.count(ClickUpTaskCreation.id)).where(
            ClickUpTaskCreation.user_id == user_id, ClickUpTaskCreation.created_at >= since)) or 0
        if recent >= CREATIONS_PER_MINUTE:
            raise ClickUpTaskError(429, "Muitas tarefas criadas em pouco tempo. Aguarde um minuto.", retry_after=60)

    def _existing(self, organization_id: UUID, key: str) -> ClickUpTaskCreation | None:
        return self.session.scalar(select(ClickUpTaskCreation).where(
            ClickUpTaskCreation.organization_id == organization_id, ClickUpTaskCreation.idempotency_key == key))

    def _resolve_replay(self, existing: ClickUpTaskCreation, *, message_id: UUID, user_id: UUID) -> ClickUpTaskCreation | None:
        """Same key: return the finished task, refuse a clash, or allow a retry of a known failure."""
        if existing.user_id != user_id or existing.message_id != message_id:
            raise ClickUpTaskError(409, "Esta chave de idempotência já foi usada em outra solicitação.")
        if existing.status == "created":
            return existing
        if existing.status == "pending":
            raise ClickUpTaskError(409, "Esta tarefa ainda está sendo criada. Aguarde alguns segundos.")
        if existing.error_code == "outcome_unknown":
            raise ClickUpTaskError(409, "Não foi possível confirmar a criação anterior. Confira a lista no ClickUp antes de tentar de novo.")
        return None

    def create(self, *, organization_id: UUID, message: ConversationMessage, user_id: UUID, user_email: str,
               idempotency_key: str, task: TaskInput) -> ClickUpTaskCreation:
        if not _KEY.match(idempotency_key or ""):
            raise ClickUpTaskError(422, "Idempotency-Key inválida.")
        source = self.source(organization_id)
        task = clean_task_input(task)
        self.require_list(source, task.list_id)
        credentials = self._credentials(source)  # before "pending": an unusable key must not leave a stuck record

        record = self._existing(organization_id, idempotency_key)
        if record is not None:
            done = self._resolve_replay(record, message_id=message.id, user_id=user_id)
            if done is not None:
                return done
            record.status, record.error_code, record.list_id = "pending", None, task.list_id
        else:
            self._rate_limit(user_id)
            record = ClickUpTaskCreation(
                organization_id=organization_id, message_id=message.id, user_id=user_id,
                idempotency_key=idempotency_key, list_id=task.list_id, status="pending")
            self.session.add(record)
        try:
            self.session.commit()  # "pending" is durable before the remote call
        except IntegrityError:
            self.session.rollback()
            raced = self._existing(organization_id, idempotency_key)
            if raced is None:
                raise
            done = self._resolve_replay(raced, message_id=message.id, user_id=user_id)
            if done is None:
                raise ClickUpTaskError(409, "Esta tarefa ainda está sendo criada. Aguarde alguns segundos.") from None
            return done

        try:
            data = self.client.create_task(
                credentials=credentials, list_id=task.list_id,
                payload=clickup_payload(task, footer=authorship_footer(user_email)))
        except (ClickUpRemoteUnauthorized, SourceRemoteUnauthorized):
            self._fail(record, "reauth_required")
            self._flag_reauth(source)
            raise ClickUpTaskError(409, "A conexão com o ClickUp expirou. Peça a um administrador para reconectar.") from None
        except SourceItemUnavailable:
            self._fail(record, "list_unavailable")
            raise ClickUpTaskError(403, "Sem permissão para criar tarefas nesta lista do ClickUp.") from None
        except ClickUpRateLimited as error:
            wait = max(1, int(error.retry_after_seconds)) if error.retry_after_seconds else 60
            self._fail(record, "rate_limited")
            raise ClickUpTaskError(429, f"O ClickUp limitou as requisições. Tente de novo em cerca de {wait} s.", retry_after=wait) from None
        except ClickUpWriteRejected:
            self._fail(record, "rejected")
            raise ClickUpTaskError(422, "O ClickUp recusou os dados da tarefa. Revise responsável, prazo e prioridade.") from None
        except ClickUpOutcomeUnknown:
            self._fail(record, "outcome_unknown")
            logger.warning("clickup task creation outcome unknown", extra={"event": "clickup_task_unknown", "creation_id": str(record.id)})
            raise ClickUpTaskError(502, "Não foi possível confirmar a criação no ClickUp. Confira a lista antes de tentar de novo.") from None
        except Exception:
            self._fail(record, "outcome_unknown")
            raise

        record.status, record.error_code = "created", None
        record.task_id = str(data["id"])[:64]
        record.task_url = _url(data.get("url")) or f"https://app.clickup.com/t/{record.task_id}"
        self.session.add(AuditLog(
            organization_id=organization_id, actor_user_id=user_id, action="clickup.task.created",
            target_type="clickup_task_creation", target_id=record.id))
        self.session.commit()
        return record

    def _fail(self, record: ClickUpTaskCreation, code: str) -> None:
        record.status, record.error_code = "failed", code
        self.session.commit()
