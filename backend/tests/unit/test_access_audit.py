import hashlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.audit import AuditWriter
from app.access.models import ApiAuditEvent
from app.core.models import Base
from tests.access_helpers import seed_tenant


def _factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_records_hash_and_length_but_never_the_query_text():
    factory = _factory()
    tenant = seed_tenant(factory, "A", "x")
    AuditWriter(factory).record(
        principal=None, organization_id=tenant.organization_id, channel="api_key", action="search",
        status="ok", http_status=200, request_id="r1", latency_ms=12, result_count=3, query="segredo Aurora",
    )
    with factory() as session:
        row = session.scalars(select(ApiAuditEvent)).one()
    assert row.query_sha256 == hashlib.sha256(b"segredo Aurora").hexdigest()
    assert row.query_length == len("segredo Aurora")
    assert "Aurora" not in repr(row.__dict__)


def test_audit_failure_never_raises():
    class Broken:
        def begin(self):
            raise RuntimeError("db down")

    AuditWriter(Broken()).record(  # type: ignore[arg-type]
        principal=None, organization_id=None, channel="mcp", action="fetch", status="error",
        http_status=500, request_id=None, latency_ms=None,
    )


def test_review_5_audit_retention_removes_only_expired_organization_events():
    from datetime import UTC, datetime, timedelta
    factory = _factory()
    a, b = seed_tenant(factory, 'A', 'x'), seed_tenant(factory, 'B', 'x')
    with factory.begin() as session:
        session.add_all([ApiAuditEvent(organization_id=tenant.organization_id, channel='api_key',
                        action='search', status='ok', http_status=200,
                        created_at=datetime.now(UTC) - timedelta(days=91)) for tenant in [a, b]])
    AuditWriter(factory).record(principal=None, organization_id=a.organization_id, channel='api_key',
                               action='search', status='ok', http_status=200, request_id=None, latency_ms=1)
    with factory() as session:
        assert len(list(session.scalars(select(ApiAuditEvent).where(ApiAuditEvent.organization_id == a.organization_id)))) == 1
        assert len(list(session.scalars(select(ApiAuditEvent).where(ApiAuditEvent.organization_id == b.organization_id)))) == 1
