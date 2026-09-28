import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.tasks import create_celery_app, schedule_connected_source_reconciliations
from app.integrations.models import DataSource
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        sync_freshness_hours=24,
        sync_scheduler_max_concurrent_per_org=3,
        sync_scheduler_failure_cooldown_minutes=30,
        sync_scheduler_slo_grace_hours=2,
    )


def create_workspace(
    session: Session,
    *,
    last_synced_at: datetime | None = None,
    status: str = "connected",
    organization: Organization | None = None,
) -> tuple[DataSource, WorkspaceFolder]:
    organization = organization or Organization(name=f"Acme {uuid4()}")
    user = User(email=f"{uuid4()}@example.test")
    session.add_all([organization, user])
    session.flush()
    source = DataSource(
        organization_id=organization.id,
        provider="google_drive",
        encrypted_credentials="ciphertext",
        status=status,
        connected_by_user_id=user.id,
        last_synced_at=last_synced_at,
    )
    session.add(source)
    session.flush()
    folder = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source.id,
        external_folder_id=str(uuid4()),
        name="Workspace",
        uniform_access_confirmed=True,
    )
    session.add(folder)
    session.commit()
    return source, folder


def schedule(session: Session, settings: SimpleNamespace, now: datetime) -> list[dict[str, object]]:
    dispatched: list[dict[str, object]] = []
    schedule_connected_source_reconciliations(
        session=session,
        settings=settings,
        send_task=lambda task, **kwargs: dispatched.append({"task": task, **kwargs}),
        now=now,
    )
    return dispatched


def test_due_source_is_enqueued(session: Session, settings: SimpleNamespace) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    _, folder = create_workspace(session)

    dispatched = schedule(session, settings, now)

    jobs = list(session.scalars(select(ProcessingJob)))
    assert len(jobs) == 1
    assert jobs[0].workspace_folder_id == folder.id
    assert dispatched == [
        {
            "task": "document_intelligence.ingestion.reconcile",
            "args": [str(jobs[0].id)],
            "countdown": 0,
        }
    ]


def test_celery_beat_uses_the_configured_scheduler_interval() -> None:
    celery_app = create_celery_app(
        SimpleNamespace(
            redis_url="redis://localhost:6379/0",
            sync_scheduler_interval_minutes=15,
        )
    )

    entry = celery_app.conf.beat_schedule["schedule-connected-source-reconciliation"]
    assert entry["task"] == "document_intelligence.ingestion.schedule"
    assert entry["schedule"] == timedelta(minutes=15)


def test_fresh_source_is_ignored(session: Session, settings: SimpleNamespace) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    create_workspace(session, last_synced_at=now - timedelta(hours=23))

    assert schedule(session, settings, now) == []
    assert list(session.scalars(select(ProcessingJob))) == []


def test_active_job_is_not_duplicated(session: Session, settings: SimpleNamespace) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    _, folder = create_workspace(session)
    existing = ProcessingJob(
        organization_id=folder.organization_id,
        workspace_folder_id=folder.id,
        status=ProcessingJobStatus.QUEUED,
        idempotency_key=str(uuid4()),
    )
    session.add(existing)
    session.commit()

    assert schedule(session, settings, now) == []
    assert list(session.scalars(select(ProcessingJob))) == [existing]


def test_reauth_required_source_is_ignored(session: Session, settings: SimpleNamespace) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    create_workspace(session, status="reauth_required")

    assert schedule(session, settings, now) == []
    assert list(session.scalars(select(ProcessingJob))) == []


def test_recent_failure_uses_cooldown_then_retries(
    session: Session, settings: SimpleNamespace
) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    _, folder = create_workspace(session)
    failed = ProcessingJob(
        organization_id=folder.organization_id,
        workspace_folder_id=folder.id,
        status=ProcessingJobStatus.FAILED,
        idempotency_key=str(uuid4()),
        completed_at=now - timedelta(minutes=29),
    )
    session.add(failed)
    session.commit()

    assert schedule(session, settings, now) == []
    assert len(list(session.scalars(select(ProcessingJob)))) == 1

    assert len(schedule(session, settings, now + timedelta(minutes=2))) == 1
    assert len(list(session.scalars(select(ProcessingJob)))) == 2


def test_per_organization_concurrency_limit_is_respected(
    session: Session, settings: SimpleNamespace
) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    organization = Organization(name="Acme")
    session.add(organization)
    session.flush()
    for _ in range(4):
        create_workspace(session, organization=organization)

    dispatched = schedule(session, settings, now)

    assert len(dispatched) == 3
    assert [item["countdown"] for item in dispatched] == [0, 5, 10]


def test_slo_warning_is_logged_for_very_stale_source(
    session: Session, settings: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    create_workspace(session, last_synced_at=now - timedelta(hours=27))

    # Attach caplog's handler directly to this logger: another test in the
    # suite may already have called configure_observability(), which sets
    # propagate=False on "document_intelligence" so records never reach the
    # root logger caplog listens on by default.
    ingestion_logger = logging.getLogger("document_intelligence.ingestion")
    ingestion_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="document_intelligence.ingestion"):
            schedule(session, settings, now)
    finally:
        ingestion_logger.removeHandler(caplog.handler)

    assert any(
        record.event == "ingestion_scheduler_slo_exceeded" for record in caplog.records
    )
