"""Tenant-scoped saved-query ownership and monthly cost guardrails."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.models import SavedQuery, UsageRecord
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.workspaces.service import WorkspaceService

ACTIVE_DOCUMENT_LIMIT = 500
MONTHLY_LIMITS = {"processed_bytes": 2_000_000_000, "embedding_tokens": 1_000_000, "questions": 1_000}


class UsageLimitExceeded(RuntimeError):
    pass


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
    def __init__(self, session: Session): self.session = session
    def check_and_record(self, *, scope: OrganizationScope, metric: str, increment: int) -> UsageRecord:
        if metric not in MONTHLY_LIMITS or increment < 0: raise ValueError("invalid usage metric")
        now = datetime.now(UTC)
        period_start = date(now.year, now.month, 1)
        record = self.session.scalar(select(UsageRecord).where(UsageRecord.organization_id == scope.organization_id, UsageRecord.period_start == period_start, UsageRecord.metric == metric).with_for_update())
        current = record.quantity if record else 0
        if current + increment > MONTHLY_LIMITS[metric]: raise UsageLimitExceeded("organization usage limit reached")
        if record is None:
            record = UsageRecord(organization_id=scope.organization_id, period_start=period_start, metric=metric, quantity=increment)
            try:
                with self.session.begin_nested():
                    self.session.add(record)
                    self.session.flush()
            except IntegrityError:
                record = self.session.scalar(select(UsageRecord).where(UsageRecord.organization_id == scope.organization_id, UsageRecord.period_start == period_start, UsageRecord.metric == metric).with_for_update())
                if record is None or record.quantity + increment > MONTHLY_LIMITS[metric]: raise UsageLimitExceeded("organization usage limit reached")
                record.quantity += increment
        else: record.quantity += increment
        self.session.flush(); return record
