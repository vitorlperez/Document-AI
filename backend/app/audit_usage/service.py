"""Tenant-scoped saved-query ownership and monthly cost guardrails."""

from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.models import SavedQuery, UsageRecord
from app.core.config import Settings, get_settings
from app.core.scoping import OrganizationScope
from app.entitlements.catalog import default_upgrade_target
from app.entitlements.errors import EntitlementError
from app.entitlements.resolver import Entitlements, entitlements_for
from app.integrations.google_drive import GoogleAccessDenied
from app.workspaces.service import WorkspaceService


def _settings(settings: Settings | None) -> Settings:
    if settings is not None: return settings
    try: return get_settings()
    except ValidationError: return Settings.model_construct()  # no DATABASE_URL (bare unit use): field defaults still apply


def active_document_limit(settings: Settings | None = None) -> int:
    return _settings(settings).active_document_limit


def monthly_limits(settings: Settings | None = None) -> dict[str, int]:
    s = _settings(settings)
    return {"processed_bytes": s.monthly_limit_processed_bytes, "embedding_tokens": s.monthly_limit_embedding_tokens,
            "questions": s.monthly_limit_questions, "ocr_pages": s.monthly_limit_ocr_pages}


def effective_monthly_limits(ent: Entitlements, settings: Settings | None = None) -> dict[str, int | None]:
    """Plan limits; ``legacy`` organizations keep reading the global ``Settings`` (the fallback), unchanged."""
    return dict(monthly_limits(settings)) if ent.source == "legacy" else ent.monthly_limits()


def effective_active_documents(ent: Entitlements, settings: Settings | None = None) -> int | None:
    return active_document_limit(settings) if ent.source == "legacy" else ent.active_documents


class UsageLimitExceeded(EntitlementError):
    """Monthly pool exhausted (HTTP 429, kept for existing clients) or the organization is read-only (402)."""

    status_code = 429

    def __init__(self, message: str = "organization usage limit reached", *, code: str = "usage_limit",
                 limit: int | None = None, used: int | None = None, upgrade_to: str | None = None,
                 status_code: int | None = None) -> None:
        super().__init__(code, message, limit=limit, used=used, upgrade_to=upgrade_to, status_code=status_code)


class SavedQueryService:
    def __init__(self, session: Session): self.session = session
    def list(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID) -> list[SavedQuery]:
        WorkspaceService(self.session).require_member_access(scope=scope, user_id=user_id, workspace_folder_id=workspace_folder_id)
        return list(self.session.scalars(select(SavedQuery).where(SavedQuery.organization_id == scope.organization_id, SavedQuery.workspace_folder_id == workspace_folder_id, SavedQuery.user_id == user_id).order_by(SavedQuery.created_at.desc(), SavedQuery.id)))
    def create(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID, name: str, query: str, filters: dict[str, object]) -> SavedQuery:
        WorkspaceService(self.session).require_member_access(scope=scope, user_id=user_id, workspace_folder_id=workspace_folder_id)
        saved = SavedQuery(organization_id=scope.organization_id, workspace_folder_id=workspace_folder_id, user_id=user_id, name=name, query=query, filters=filters)
        self.session.add(saved); self.session.flush(); return saved
    def update(self, *, scope: OrganizationScope, user_id: UUID, saved_query_id: UUID, name: str) -> SavedQuery:
        saved = self._own(scope=scope, user_id=user_id, saved_query_id=saved_query_id); saved.name=name; self.session.flush(); return saved
    def set_followed(self, *, scope: OrganizationScope, user_id: UUID, saved_query_id: UUID, followed: bool) -> SavedQuery:
        saved = self._own(scope=scope, user_id=user_id, saved_query_id=saved_query_id)
        saved.followed = followed
        if not followed: saved.last_answer = None; saved.last_checked_at = None
        self.session.flush(); return saved
    def delete(self, *, scope: OrganizationScope, user_id: UUID, saved_query_id: UUID) -> None:
        self.session.delete(self._own(scope=scope, user_id=user_id, saved_query_id=saved_query_id)); self.session.flush()
    def _own(self, *, scope: OrganizationScope, user_id: UUID, saved_query_id: UUID) -> SavedQuery:
        saved = self.session.scalar(select(SavedQuery).where(SavedQuery.id == saved_query_id, SavedQuery.organization_id == scope.organization_id, SavedQuery.user_id == user_id))
        if saved is None: raise GoogleAccessDenied("saved query access denied")
        WorkspaceService(self.session).require_member_access(
            scope=scope,
            user_id=user_id,
            workspace_folder_id=saved.workspace_folder_id,
        )
        return saved


class UsageService:
    def __init__(self, session: Session, settings: Settings | None = None): self.session = session; self.settings = settings
    def check_and_record(self, *, scope: OrganizationScope, metric: str, increment: int) -> UsageRecord:
        ent = entitlements_for(self.session, scope.organization_id, self.settings)
        limits = effective_monthly_limits(ent, self.settings)
        if metric not in limits or increment < 0: raise ValueError("invalid usage metric")
        if ent.read_only:
            raise UsageLimitExceeded("organization is read-only until a plan is active", code="read_only", status_code=402,
                                     upgrade_to=default_upgrade_target(ent.plan_key, ent.account_type))
        cap = limits[metric]
        if cap is None: cap = 2**62  # unlimited
        limits = {**limits, metric: cap}
        now = datetime.now(UTC)
        period_start = date(now.year, now.month, 1)
        record = self.session.scalar(select(UsageRecord).where(UsageRecord.organization_id == scope.organization_id, UsageRecord.period_start == period_start, UsageRecord.metric == metric).with_for_update())
        current = (record.quantity if record else 0) + self._trial_carryover(scope, ent, metric, period_start)
        if current + increment > limits[metric]: raise self._exceeded(ent, limits[metric], current)
        if record is None:
            record = UsageRecord(organization_id=scope.organization_id, period_start=period_start, metric=metric, quantity=increment)
            try:
                with self.session.begin_nested():
                    self.session.add(record)
                    self.session.flush()
            except IntegrityError:
                record = self.session.scalar(select(UsageRecord).where(UsageRecord.organization_id == scope.organization_id, UsageRecord.period_start == period_start, UsageRecord.metric == metric).with_for_update())
                if record is None or record.quantity + increment > limits[metric]: raise self._exceeded(ent, limits[metric], record.quantity if record else 0)
                record.quantity += increment
        else: record.quantity += increment
        self.session.flush(); return record

    @staticmethod
    def _exceeded(ent: Entitlements, limit: int, used: int) -> UsageLimitExceeded:
        return UsageLimitExceeded(limit=limit, used=used, upgrade_to=default_upgrade_target(ent.plan_key, ent.account_type))

    def _trial_carryover(self, scope: OrganizationScope, ent: Entitlements, metric: str, period_start: date) -> int:
        """A 14-day trial may span two calendar months: its pool is the sum since the trial began."""
        if ent.source != "trial": return 0
        from sqlalchemy import func

        from app.organizations.models import Organization
        started = self.session.scalar(select(Organization.trial_started_at).where(Organization.id == scope.organization_id))
        if started is None: return 0
        return int(self.session.scalar(select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.organization_id == scope.organization_id, UsageRecord.metric == metric,
            UsageRecord.period_start >= date(started.year, started.month, 1), UsageRecord.period_start < period_start)) or 0)


def usage_summary(session: Session, *, scope: OrganizationScope, settings: Settings | None = None) -> dict[str, object]:
    """Current-month consumption against monthly_limits() and the active-document cap."""
    from sqlalchemy import func

    from app.knowledge.models import Document

    now = datetime.now(UTC)
    period_start = date(now.year, now.month, 1)
    used = dict(session.execute(
        select(UsageRecord.metric, UsageRecord.quantity).where(
            UsageRecord.organization_id == scope.organization_id, UsageRecord.period_start == period_start)
    ).all())
    ent = entitlements_for(session, scope.organization_id, settings)
    metrics = []
    for metric, limit in effective_monthly_limits(ent, settings).items():
        metrics.append(_usage_row(metric, int(used.get(metric, 0)), limit))
    documents = session.scalar(select(func.count()).select_from(Document).where(
        Document.organization_id == scope.organization_id, Document.index_status == "indexed")) or 0
    return {"period_start": period_start.isoformat(), "metrics": metrics,
            "active_documents": _usage_row("active_documents", int(documents), effective_active_documents(ent, settings)),
            "plan_key": ent.plan_key, "account_type": ent.account_type, "entitlement_source": ent.source,
            "read_only": ent.read_only, "trial_ends_at": ent.trial_ends_at.isoformat() if ent.trial_ends_at else None}


def _usage_row(metric: str, used: int, limit: int | None) -> dict[str, object]:
    ratio = used / limit if limit else 0.0
    level = "exceeded" if ratio >= 1 else "warning" if ratio >= 0.8 else "ok"
    return {"metric": metric, "used": used, "limit": limit, "ratio": round(ratio, 4), "level": level}
