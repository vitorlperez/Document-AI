from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.ingestion.extraction.cache import CachingOcr, purge_cache
from app.ingestion.models import ExtractionCache
from app.organizations.models import Organization
from app.ingestion import service  # registers referenced models


class Engine:
    name, version = "fake", "1"
    def __init__(self): self.calls = 0
    def recognize(self, pdf, **kwargs): self.calls += 1; return ["ação"]


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


def test_cache_tenant_version_and_none(factory):
    inner = Engine()
    org = uuid4()
    engine = CachingOcr(inner, factory, org)
    for _ in range(2): assert engine.recognize(b"x", page_count=1, cache_key="key") == ["ação"]
    assert inner.calls == 1
    CachingOcr(inner, factory, uuid4()).recognize(b"x",page_count=1,cache_key="key")
    inner.version = "2"
    CachingOcr(inner, factory, org).recognize(b"x",page_count=1,cache_key="key")
    engine.recognize(b"x",page_count=1)
    engine.recognize(b"x",page_count=1)
    assert inner.calls == 5


def test_expired_cache_is_miss_and_purge_only_old(factory):
    inner, org = Engine(), uuid4()
    cached = CachingOcr(inner, factory, org)
    cached.recognize(b"x",page_count=1,cache_key="key")
    with factory() as s:
        row = s.scalar(select(ExtractionCache))
        row.created_at = datetime.now(UTC)-timedelta(days=91)
        s.commit()
    cached.recognize(b"x",page_count=1,cache_key="fresh")
    with factory() as s:
        assert purge_cache(s) == 1
        s.commit()
        assert len(list(s.scalars(select(ExtractionCache)))) == 1
