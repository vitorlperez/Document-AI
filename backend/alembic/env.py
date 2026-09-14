from sqlalchemy import engine_from_config, pool

from alembic import context
from app.audit_usage.models import AuditLog  # noqa: F401
from app.core.config import get_settings
from app.core.models import Base
from app.identity.models import User  # noqa: F401
from app.ingestion.models import ProcessingJob  # noqa: F401
from app.knowledge.models import Document, DocumentChunk  # noqa: F401
from app.library.models import LibraryNode  # noqa: F401
from app.organizations.models import Membership, Organization  # noqa: F401
from app.workspaces.models import WorkspaceFolder  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
