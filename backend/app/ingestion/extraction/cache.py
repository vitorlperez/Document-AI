"""OCR result cache. One session per call: extractions run in worker threads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.ingestion.models import ExtractionCache

TTL_DAYS = 90


class CachingOcr:
    def __init__(self, inner, session_factory, organization_id, ttl_days: int = TTL_DAYS) -> None:
        self.inner, self.session_factory = inner, session_factory
        self.organization_id, self.ttl = organization_id, timedelta(days=ttl_days)
        self.name, self.version = inner.name, inner.version

    def _scope(self):
        return (
            ExtractionCache.organization_id == self.organization_id,
            ExtractionCache.engine == self.inner.name,
            ExtractionCache.engine_version == self.inner.version,
        )

    def recognize(self, pdf, *, page_count, cache_key=None):
        if cache_key is None:
            return self.inner.recognize(pdf, page_count=page_count)
        with self.session_factory() as session:
            hit = session.scalar(
                select(ExtractionCache).where(
                    *self._scope(),
                    ExtractionCache.cache_key == cache_key,
                    ExtractionCache.created_at >= datetime.now(UTC) - self.ttl,
                )
            )
            if hit is not None and len(hit.page_texts) == page_count:
                return list(hit.page_texts)
        pages = self.inner.recognize(pdf, page_count=page_count, cache_key=cache_key)
        with self.session_factory() as session:
            try:
                session.add(
                    ExtractionCache(
                        organization_id=self.organization_id,
                        engine=self.inner.name,
                        engine_version=self.inner.version,
                        cache_key=cache_key,
                        page_texts=list(pages),
                    )
                )
                session.commit()
            except IntegrityError:
                session.rollback()
        return pages


def purge_cache(session, ttl_days: int = TTL_DAYS) -> int:
    result = session.execute(
        delete(ExtractionCache).where(
            ExtractionCache.created_at < datetime.now(UTC) - timedelta(days=ttl_days)
        )
    )
    return result.rowcount
