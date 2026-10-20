"""Automations: recurring cited reports over folders, run with their creator's permissions (specs/automations-api.md)."""
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.automations.executor import accessible_folders
from app.automations.models import Automation, AutomationRun
from app.automations.report_pdf import (
    DEFAULT_TIMEZONE,
    ReportMeta,
    ReportSource,
    to_report_pdf,
    trigger_label,
)
from app.automations.schedule import (
    InvalidTriggerConfig,
    compute_next_run,
    normalize_trigger_config,
)
from app.automations.scope import (
    MAX_SCOPE_NODES,
    legacy_folder_ids,
    node_access,
    node_paths,
    resolve_nodes,
    scope_node_ids,
)
from app.automations.space_access import hidden_result, runs_visibility
from app.automations.triggers import queue_run
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.untrusted import sanitize_label
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder

router = APIRouter(tags=["automations"])
MAX_AUTOMATIONS_PER_ORGANIZATION = 20
MAX_SCOPE_FOLDERS = 20
OUTPUT_FORMATS = {"email", "pdf"}


class ScopeInput(BaseModel):
    """Library folders at any depth (``node_ids``); ``workspace_folder_ids`` is the legacy whole-folder scope."""

    node_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_SCOPE_NODES)
    workspace_folder_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_SCOPE_FOLDERS)

    @model_validator(mode="after")
    def exactly_one(self) -> "ScopeInput":
        if (self.node_ids is None) == (self.workspace_folder_ids is None):
            raise ValueError("send node_ids or workspace_folder_ids")
        return self


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    trigger_kind: Literal["schedule", "folder_changed"]
    trigger_config: dict[str, object] = Field(default_factory=dict)
    scope: ScopeInput
    prompt: str = Field(min_length=1, max_length=1000)
    template: Literal["summary", "table", "alert"] = "summary"
    output_formats: list[str] = Field(default_factory=lambda: ["email"])
    recipient_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    trigger_kind: Literal["schedule", "folder_changed"] | None = None
    trigger_config: dict[str, object] | None = None
    scope: ScopeInput | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=1000)
    template: Literal["summary", "table", "alert"] | None = None
    output_formats: list[str] | None = None
    recipient_user_ids: list[UUID] | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class EnabledInput(BaseModel):
    enabled: bool


def _membership(session: Session, organization_id: UUID, user: User) -> Membership:
    member = session.scalar(select(Membership).where(
        Membership.organization_id == organization_id, Membership.user_id == user.id, Membership.is_active.is_(True)))
    if member is None:
        raise HTTPException(403, "not allowed")
    return member


def _is_admin(member: Membership) -> bool:
    return member.role in (MembershipRole.OWNER, MembershipRole.ADMIN)


def _load(session: Session, organization_id: UUID, automation_id: UUID, user: User) -> tuple[Automation, Membership]:
    member = _membership(session, organization_id, user)
    automation = session.scalar(select(Automation).where(
        Automation.id == automation_id, Automation.organization_id == organization_id))
    if automation is None or not (_is_admin(member) or automation.created_by_user_id == user.id):
        raise HTTPException(404, "automation not found")
    return automation, member


def _load_reader(session: Session, organization_id: UUID, automation_id: UUID, user: User) -> Automation:
    """Read-only access: creator/admin, or a listed recipient who still has access to every scope folder right now."""
    member = _membership(session, organization_id, user)
    automation = session.scalar(select(Automation).where(
        Automation.id == automation_id, Automation.organization_id == organization_id))
    if automation is None:
        raise HTTPException(404, "automation not found")
    if _is_admin(member) or automation.created_by_user_id == user.id:
        return automation
    if str(user.id) not in {str(item) for item in automation.recipients or []}:
        raise HTTPException(404, "automation not found")
    scope = OrganizationScope(organization_id)
    nodes = scope_node_ids(automation.scope)
    if nodes:
        allowed = node_access(session, scope, user.id, nodes) == "ok"
    else:
        folders = set(legacy_folder_ids(automation.scope))
        folder_access = accessible_folders(session, scope, user.id)
        allowed = bool(folders) and folder_access is not None and folders <= folder_access
    if not allowed:
        raise HTTPException(404, "automation not found")
    return automation


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _serialize_run(run: AutomationRun, *, visible: bool = True) -> dict[str, object]:
    if not visible:  # the viewer lost access to something this run was made of (ADR-0021 §8.2)
        return {"id": str(run.id), "automation_id": str(run.automation_id), "status": run.status,
                "trigger_ref": run.trigger_ref, "started_at": _iso(run.started_at), "finished_at": _iso(run.finished_at),
                "documents_considered": run.documents_considered, "questions_used": run.questions_used,
                "error_code": run.error_code, "result": hidden_result(), "pdf_available": False}
    return {"id": str(run.id), "automation_id": str(run.automation_id), "status": run.status, "trigger_ref": run.trigger_ref,
            "started_at": _iso(run.started_at), "finished_at": _iso(run.finished_at),
            "documents_considered": run.documents_considered, "questions_used": run.questions_used,
            "error_code": run.error_code, "result": run.result, "pdf_available": run.status == "ok"}


def _serialize_scope(session: Session, automation: Automation) -> dict[str, object]:
    scope = dict(automation.scope or {})
    node_ids = scope_node_ids(scope)
    if node_ids:  # display names and full paths; a vanished folder is simply missing from ``folders``
        paths = node_paths(session, OrganizationScope(automation.organization_id), node_ids)
        scope["folders"] = [{"node_id": str(item), "name": paths[item].rsplit("/", 1)[-1], "path": paths[item]}
                            for item in node_ids if item in paths]
    return scope


def _folder_labels(session: Session, automation: Automation) -> tuple[str, ...]:
    node_ids = scope_node_ids(automation.scope)
    if node_ids:
        paths = node_paths(session, OrganizationScope(automation.organization_id), node_ids)
        return tuple(paths[item] for item in node_ids if item in paths)
    ids = legacy_folder_ids(automation.scope)
    names = session.scalars(select(WorkspaceFolder.name).where(
        WorkspaceFolder.organization_id == automation.organization_id, WorkspaceFolder.id.in_(ids))) if ids else []
    return tuple(names)


def _serialize(session: Session, automation: Automation) -> dict[str, object]:
    ids = [UUID(str(item)) for item in automation.recipients or []]
    emails = dict(session.execute(select(User.id, User.email).where(User.id.in_(ids))).all()) if ids else {}
    last = session.scalar(select(AutomationRun).where(AutomationRun.automation_id == automation.id)
                          .order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc()).limit(1))
    return {"id": str(automation.id), "name": automation.name, "enabled": automation.enabled,
            "trigger_kind": automation.trigger_kind, "trigger_config": automation.trigger_config,
            "scope": _serialize_scope(session, automation),
            "prompt": automation.prompt, "template": automation.template, "output_formats": automation.output_formats,
            "recipients": [{"user_id": str(item), "email": emails.get(item)} for item in ids],
            "created_by_user_id": str(automation.created_by_user_id), "last_run_at": _iso(automation.last_run_at),
            "next_run_at": _iso(automation.next_run_at),
            "last_run": None if last is None else {"id": str(last.id), "status": last.status, "finished_at": _iso(last.finished_at)},
            "created_at": _iso(automation.created_at)}


def _validate_formats(formats: list[str]) -> list[str]:
    if not set(formats) <= OUTPUT_FORMATS:
        raise HTTPException(422, "invalid_output_formats")
    return sorted(set(formats))


def _validate_trigger(kind: str, config: dict[str, object]) -> dict[str, object]:
    try:
        return normalize_trigger_config(kind, config)
    except InvalidTriggerConfig as error:
        raise HTTPException(422, "invalid_trigger_config") from error


def _validate_scope(session: Session, organization_id: UUID, creator_id: UUID, scope: ScopeInput) -> dict[str, object]:
    if scope.node_ids is not None:
        node_ids = list(dict.fromkeys(scope.node_ids))
        try:
            resolve_nodes(session, OrganizationScope(organization_id), creator_id, node_ids)
        except (SyncAccessDenied, ValueError) as error:  # not a member, foreign/unknown node, a file, or nothing indexed
            raise HTTPException(422, "scope_not_allowed") from error
        return {"node_ids": [str(item) for item in node_ids]}
    ids = list(dict.fromkeys(scope.workspace_folder_ids or []))
    allowed = accessible_folders(session, OrganizationScope(organization_id), creator_id)
    if allowed is None or not set(ids) <= allowed:
        raise HTTPException(422, "scope_not_allowed")
    return {"workspace_folder_ids": [str(item) for item in ids]}


def _validate_recipients(session: Session, organization_id: UUID, actor: Membership, creator_id: UUID,
                         recipient_ids: list[UUID]) -> list[str]:
    ids = [item for item in dict.fromkeys(recipient_ids) if item != creator_id]
    if ids and not _is_admin(actor):
        raise HTTPException(403, "owner or admin required")
    if ids:
        found = set(session.scalars(select(Membership.user_id).where(
            Membership.organization_id == organization_id, Membership.is_active.is_(True), Membership.user_id.in_(ids))))
        if found != set(ids):
            raise HTTPException(422, "recipient_not_member")
    return [str(creator_id), *[str(item) for item in ids]]


def _refresh_schedule(automation: Automation) -> None:
    if automation.enabled and automation.trigger_kind == "schedule":
        automation.next_run_at = compute_next_run(automation.trigger_config, datetime.now(UTC))
    else:
        automation.next_run_at = None


@router.get("/organizations/{organization_id}/automation-recipients")
def list_recipients(organization_id: UUID, workspace_folder_ids: list[UUID] = Query(default_factory=list, max_length=MAX_SCOPE_FOLDERS),
                    node_ids: list[UUID] = Query(default_factory=list, max_length=MAX_SCOPE_NODES),
                    user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    if not _is_admin(_membership(session, organization_id, user)):
        raise HTTPException(403, "owner or admin required")
    folders, nodes = set(workspace_folder_ids), list(dict.fromkeys(node_ids))
    if folders and nodes:
        raise HTTPException(422, "scope_not_allowed")
    if nodes:
        try:
            resolve_nodes(session, OrganizationScope(organization_id), user.id, nodes)
        except (SyncAccessDenied, ValueError) as error:
            raise HTTPException(422, "scope_not_allowed") from error
    if folders:
        known = set(session.scalars(select(WorkspaceFolder.id).where(
            WorkspaceFolder.organization_id == organization_id, WorkspaceFolder.id.in_(folders))))
        if known != folders:
            raise HTTPException(422, "scope_not_allowed")
    rows = session.execute(select(Membership.user_id, Membership.role, User.email).join(User, User.id == Membership.user_id).where(
        Membership.organization_id == organization_id, Membership.is_active.is_(True)).order_by(User.email, User.id)).all()
    scope = OrganizationScope(organization_id)
    items = []
    for user_id, role, email in rows:
        has_access: bool | None = None
        if nodes:
            has_access = node_access(session, scope, user_id, nodes) == "ok"
        elif folders:
            allowed = accessible_folders(session, scope, user_id)
            has_access = allowed is not None and folders <= allowed
        items.append({"user_id": str(user_id), "name": email.split("@", 1)[0], "email": email, "role": role.value,
                      "has_access": has_access, "is_you": user_id == user.id})
    return {"items": items}


@router.get("/organizations/{organization_id}/automations")
def list_automations(organization_id: UUID, user: User = Depends(current_user),
                     session: Session = Depends(database_session)) -> dict[str, object]:
    member = _membership(session, organization_id, user)
    statement = select(Automation).where(Automation.organization_id == organization_id)
    if not _is_admin(member):
        statement = statement.where(Automation.created_by_user_id == user.id)
    rows = session.scalars(statement.order_by(Automation.created_at.desc(), Automation.id))
    return {"limit": MAX_AUTOMATIONS_PER_ORGANIZATION, "items": [_serialize(session, item) for item in rows]}


@router.post("/organizations/{organization_id}/automations", status_code=201)
def create_automation(organization_id: UUID, payload: AutomationCreate, user: User = Depends(current_user),
                      session: Session = Depends(database_session)) -> dict[str, object]:
    member = _membership(session, organization_id, user)
    count = len(session.scalars(select(Automation.id).where(Automation.organization_id == organization_id)).all())
    if count >= MAX_AUTOMATIONS_PER_ORGANIZATION:
        raise HTTPException(409, "automation_limit_reached")
    automation = Automation(
        organization_id=organization_id, created_by_user_id=user.id, name=payload.name.strip(),
        enabled=payload.enabled, trigger_kind=payload.trigger_kind,
        trigger_config=_validate_trigger(payload.trigger_kind, payload.trigger_config),
        scope=_validate_scope(session, organization_id, user.id, payload.scope), prompt=payload.prompt.strip(),
        template=payload.template, output_formats=_validate_formats(payload.output_formats),
        recipients=_validate_recipients(session, organization_id, member, user.id, payload.recipient_user_ids))
    _refresh_schedule(automation)
    session.add(automation)
    session.flush()
    return _serialize(session, automation)


@router.get("/organizations/{organization_id}/automations/{automation_id}")
def get_automation(organization_id: UUID, automation_id: UUID, user: User = Depends(current_user),
                   session: Session = Depends(database_session)) -> dict[str, object]:
    automation, _ = _load(session, organization_id, automation_id, user)
    return _serialize(session, automation)


@router.patch("/organizations/{organization_id}/automations/{automation_id}")
def update_automation(organization_id: UUID, automation_id: UUID, payload: AutomationPatch, user: User = Depends(current_user),
                      session: Session = Depends(database_session)) -> dict[str, object]:
    automation, member = _load(session, organization_id, automation_id, user)
    given = payload.model_fields_set
    kind = payload.trigger_kind if "trigger_kind" in given and payload.trigger_kind else automation.trigger_kind
    if "trigger_kind" in given or "trigger_config" in given:
        config = payload.trigger_config if "trigger_config" in given and payload.trigger_config is not None else (
            automation.trigger_config if kind == automation.trigger_kind else {})
        automation.trigger_config = _validate_trigger(kind, config)
        automation.trigger_kind = kind
    if payload.name is not None:
        automation.name = payload.name.strip()
    if payload.prompt is not None:
        automation.prompt = payload.prompt.strip()
    if payload.template is not None:
        automation.template = payload.template
    if payload.output_formats is not None:
        automation.output_formats = _validate_formats(payload.output_formats)
    if payload.scope is not None:
        automation.scope = _validate_scope(session, organization_id, automation.created_by_user_id, payload.scope)
    if payload.recipient_user_ids is not None:
        automation.recipients = _validate_recipients(session, organization_id, member, automation.created_by_user_id,
                                                     payload.recipient_user_ids)
    if payload.enabled is not None:
        automation.enabled = payload.enabled
    _refresh_schedule(automation)
    session.flush()
    return _serialize(session, automation)


@router.delete("/organizations/{organization_id}/automations/{automation_id}", status_code=204)
def delete_automation(organization_id: UUID, automation_id: UUID, user: User = Depends(current_user),
                      session: Session = Depends(database_session)) -> Response:
    automation, _ = _load(session, organization_id, automation_id, user)
    session.execute(delete(AutomationRun).where(AutomationRun.automation_id == automation.id))
    session.delete(automation)
    return Response(status_code=204)


@router.put("/organizations/{organization_id}/automations/{automation_id}/enabled")
def set_enabled(organization_id: UUID, automation_id: UUID, payload: EnabledInput, user: User = Depends(current_user),
                session: Session = Depends(database_session)) -> dict[str, object]:
    automation, _ = _load(session, organization_id, automation_id, user)
    automation.enabled = payload.enabled
    _refresh_schedule(automation)
    session.flush()
    return _serialize(session, automation)


@router.post("/organizations/{organization_id}/automations/{automation_id}/run", status_code=202)
def run_now(organization_id: UUID, automation_id: UUID, request: Request, user: User = Depends(current_user),
            session: Session = Depends(database_session)) -> dict[str, object]:
    automation, _ = _load(session, organization_id, automation_id, user)
    run = queue_run(session, automation, f"manual:{uuid4()}")
    if run is None:  # uuid collision: practically unreachable
        raise HTTPException(409, "run already queued")
    session.commit()
    try:
        request.app.state.automation_send_task("document_intelligence.ingestion.run_automation", args=[str(run.id)])
    except Exception as error:
        raise HTTPException(503, "automation dispatch unavailable") from error
    return _serialize_run(run)


def _run_of(session: Session, automation: Automation, run_id: UUID) -> AutomationRun:
    run = session.scalar(select(AutomationRun).where(AutomationRun.id == run_id, AutomationRun.automation_id == automation.id))
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.get("/organizations/{organization_id}/automations/{automation_id}/runs")
def list_runs(organization_id: UUID, automation_id: UUID, limit: int = Query(20, ge=1, le=100),
              user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    automation, _ = _load(session, organization_id, automation_id, user)
    rows = session.scalars(select(AutomationRun).where(AutomationRun.automation_id == automation.id)
                           .order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc()).limit(limit))
    rows = list(rows)
    seen = runs_visibility(session, organization_id, user.id, rows)
    return {"items": [_serialize_run(item, visible=seen[item.id]) for item in rows]}


@router.get("/organizations/{organization_id}/automations/{automation_id}/runs/{run_id}")
def get_run(organization_id: UUID, automation_id: UUID, run_id: UUID, user: User = Depends(current_user),
            session: Session = Depends(database_session)) -> dict[str, object]:
    automation = _load_reader(session, organization_id, automation_id, user)
    run = _run_of(session, automation, run_id)
    return _serialize_run(run, visible=runs_visibility(session, organization_id, user.id, [run])[run.id])


@router.get("/organizations/{organization_id}/automations/{automation_id}/runs/{run_id}/view")
def view_run(organization_id: UUID, automation_id: UUID, run_id: UUID, user: User = Depends(current_user),
             session: Session = Depends(database_session)) -> dict[str, object]:
    """Read-only report view for e-mail links (recipients included): name, folders and the run, nothing editable."""
    automation = _load_reader(session, organization_id, automation_id, user)
    run = _run_of(session, automation, run_id)
    return {"automation": {"id": str(automation.id), "name": automation.name,
                           "folders": list(_folder_labels(session, automation))},
            "run": _serialize_run(run, visible=runs_visibility(session, organization_id, user.id, [run])[run.id])}


@router.get("/organizations/{organization_id}/automations/{automation_id}/runs/{run_id}/pdf")
def run_pdf(organization_id: UUID, automation_id: UUID, run_id: UUID, user: User = Depends(current_user),
            session: Session = Depends(database_session)) -> Response:
    automation = _load_reader(session, organization_id, automation_id, user)
    run = _run_of(session, automation, run_id)
    if not runs_visibility(session, organization_id, user.id, [run])[run.id]:
        raise HTTPException(404, "run_has_no_result")
    answer = (run.result or {}).get("answer")
    if not isinstance(answer, str) or not answer:
        raise HTTPException(404, "run_has_no_result")
    sources = []
    for item in (run.result or {}).get("citations") or []:
        if isinstance(item, dict) and isinstance(item.get("document_name"), str):
            url = item.get("source_url")
            page = item.get("page_number")
            sources.append(ReportSource(
                sanitize_label(item["document_name"]),
                url if isinstance(url, str) and url.startswith(("http://", "https://")) else "",
                str(item.get("excerpt") or ""), page if isinstance(page, int) and not isinstance(page, bool) else None))
    config = automation.trigger_config or {}
    meta = ReportMeta(
        automation_name=automation.name, folders=_folder_labels(session, automation),
        executed_at=run.finished_at or run.started_at or run.created_at,
        trigger=trigger_label(automation.trigger_kind, config, run.trigger_ref),
        timezone=str(config.get("timezone") or DEFAULT_TIMEZONE), documents_considered=run.documents_considered)
    body, media_type = to_report_pdf(meta, answer, sources), "application/pdf"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", automation.name).strip("-")[:40].lower() or "automacao"
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="arquivio-{slug}.pdf"', "Cache-Control": "no-store"})
