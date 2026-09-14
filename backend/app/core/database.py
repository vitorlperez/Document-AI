import logging
import time
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

logger = logging.getLogger("document_intelligence.readiness")


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 2},
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def database_is_ready(engine: Engine) -> bool:
    """Perform one bounded non-sensitive database query for readiness."""
    started_at = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info(
            "database readiness complete",
            extra={
                "event": "readiness_check",
                "result": "ready",
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return True
    except SQLAlchemyError:  # Database driver details must not escape an operational endpoint.
        logger.warning(
            "database readiness unavailable",
            extra={
                "event": "readiness_check",
                "result": "unavailable",
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return False


def session_dependency(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
