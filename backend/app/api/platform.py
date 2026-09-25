"""Platform-staff support endpoints, deliberately separate from tenant APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import IngestionService
from app.organizations.staff_access import PlatformStaffAccessService, StaffAccessDenied
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/platform", tags=["platform-support"])


@router.get("/companies")
def supported_companies(
    user: User = Depends(current_user), session: Session = Depends(database_session)
) -> list[dict[str, str]]:
    service = PlatformStaffAccessService(session)
    if not service.is_platform_staff(user_id=user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    return [
        {
            "organization_id": str(company.organization_id),
            "name": company.organization_name,
        }
        for company in service.all_organizations(user_id=user.id)
    ]


@router.get("/companies/{organization_id}/overview")
def supported_company_overview(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    scope = OrganizationScope(organization_id)
    service = PlatformStaffAccessService(session)
    try:
        company = service.require_organization_access(user_id=user.id, organization_id=organization_id)
    except StaffAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    service.record_organization_access(user_id=user.id, organization=company)
    folders = WorkspaceService(session).support_metadata(scope=scope)
    failure_summary = IngestionService(session).support_failure_summary(scope=scope)
    return {
        "organization_id": str(company.organization_id),
        "name": company.organization_name,
        "folders": [
            {
                "id": str(folder.id),
                "name": folder.name,
                "status": folder.status,
                "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None,
                "failure_summary": [
                    {"error_code": error_code, "count": count}
                    for error_code, count in failure_summary.get(folder.id, [])
                ],
            }
            for folder in folders
        ],
    }
