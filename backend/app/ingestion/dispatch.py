"""Celery dispatch boundary used by the API after a sync job is committed."""

from typing import Protocol
from uuid import UUID

from celery import Celery


class IngestionDispatcher(Protocol):
    def dispatch(self, *, job_id: UUID) -> None: ...


class CeleryIngestionDispatcher:
    def __init__(self, celery_app: Celery):
        self.celery_app = celery_app

    def dispatch(self, *, job_id: UUID) -> None:
        try:
            self.celery_app.send_task("document_intelligence.ingestion.reconcile", args=[str(job_id)])
        except Exception as error:
            raise RuntimeError("ingestion dispatch unavailable") from error
