from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.service import MONTHLY_LIMITS, UsageLimitExceeded, UsageService
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.organizations.models import Organization


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


def organization(session: Session) -> Organization:
    value = Organization(name=str(uuid4()))
    session.add(value); session.commit()
    return value


def test_usage_accumulates_by_tenant_month_and_blocks_only_excess_metric(session: Session) -> None:
    first, second = organization(session), organization(session)
    usage = UsageService(session)
    first_record = usage.check_and_record(scope=OrganizationScope(first.id), metric="questions", increment=MONTHLY_LIMITS["questions"])
    second_record = usage.check_and_record(scope=OrganizationScope(second.id), metric="questions", increment=1)
    session.commit()

    assert first_record.quantity == MONTHLY_LIMITS["questions"]
    assert second_record.quantity == 1
    with pytest.raises(UsageLimitExceeded):
        usage.check_and_record(scope=OrganizationScope(first.id), metric="questions", increment=1)
    processed_record = usage.check_and_record(scope=OrganizationScope(first.id), metric="processed_bytes", increment=1)
    assert processed_record.quantity == 1


@pytest.mark.parametrize("metric,increment", [("unknown", 1), ("questions", -1)])
def test_usage_rejects_invalid_metric_or_negative_increment(session: Session, metric: str, increment: int) -> None:
    with pytest.raises(ValueError):
        UsageService(session).check_and_record(scope=OrganizationScope(uuid4()), metric=metric, increment=increment)
