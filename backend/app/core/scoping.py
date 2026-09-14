from dataclasses import dataclass
from uuid import UUID


class TenantScopeRequired(ValueError):
    pass


@dataclass(frozen=True)
class OrganizationScope:
    organization_id: UUID

    def __post_init__(self) -> None:
        if self.organization_id is None:
            raise TenantScopeRequired("organization scope is required")
