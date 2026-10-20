from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.service import UsageLimitExceeded, UsageService, monthly_limits
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
    first_record = usage.check_and_record(scope=OrganizationScope(first.id), metric="questions", increment=monthly_limits()["questions"])
    second_record = usage.check_and_record(scope=OrganizationScope(second.id), metric="questions", increment=1)
    session.commit()

    assert first_record.quantity == monthly_limits()["questions"]
    assert second_record.quantity == 1
    with pytest.raises(UsageLimitExceeded):
        usage.check_and_record(scope=OrganizationScope(first.id), metric="questions", increment=1)
    processed_record = usage.check_and_record(scope=OrganizationScope(first.id), metric="processed_bytes", increment=1)
    assert processed_record.quantity == 1


@pytest.mark.parametrize("metric,increment", [("unknown", 1), ("questions", -1)])
def test_usage_rejects_invalid_metric_or_negative_increment(session: Session, metric: str, increment: int) -> None:
    with pytest.raises(ValueError):
        UsageService(session).check_and_record(scope=OrganizationScope(uuid4()), metric=metric, increment=increment)


def test_limits_come_from_one_settings_source_with_library_scale_defaults() -> None:
    from app.audit_usage.service import active_document_limit
    from app.core.config import Settings

    defaults = Settings(database_url="postgresql+psycopg://u:p@localhost/db", _env_file=None)
    assert active_document_limit(defaults) == 3_000
    assert monthly_limits(defaults) == {
        "processed_bytes": 12_000_000_000, "embedding_tokens": 10_000_000, "questions": 1_000, "ocr_pages": 2_000}
    # Indexing 3,000 docs of ~5 chunks (~1,000 chars, len/4 tokens) must not hit the monthly embedding budget first.
    assert 3_000 * 5 * 250 < monthly_limits(defaults)["embedding_tokens"]
    tuned = Settings(database_url="postgresql+psycopg://u:p@localhost/db", active_document_limit=10_000,
                     monthly_limit_embedding_tokens=5, _env_file=None)
    assert active_document_limit(tuned) == 10_000
    assert monthly_limits(tuned)["embedding_tokens"] == 5


def test_usage_service_enforces_configured_monthly_limit(session: Session) -> None:
    from app.core.config import Settings

    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", monthly_limit_embedding_tokens=10, _env_file=None)
    usage = UsageService(session, settings)
    org = organization(session)
    usage.check_and_record(scope=OrganizationScope(org.id), metric="embedding_tokens", increment=10)
    with pytest.raises(UsageLimitExceeded):
        usage.check_and_record(scope=OrganizationScope(org.id), metric="embedding_tokens", increment=1)
