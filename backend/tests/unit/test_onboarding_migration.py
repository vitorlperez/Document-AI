import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_migration_preserves_existing_tenants_and_leaves_new_tenants_pending():
    path = Path(__file__).parents[2] / "alembic/versions/20260930_0026_organization_onboarding.py"
    spec = importlib.util.spec_from_file_location("onboarding_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("CREATE TABLE memberships (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO organizations VALUES (1, 'Existing')"))
        connection.execute(text("INSERT INTO memberships VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        old = connection.execute(text("SELECT onboarding_step, onboarding_completed_at FROM organizations WHERE id = 1")).one()
        assert old.onboarding_step == "complete" and old.onboarding_completed_at is not None
        assert connection.scalar(text("SELECT tour_completed_at FROM memberships WHERE id = 1")) is not None
        connection.execute(text("INSERT INTO organizations (id, name) VALUES (2, 'New')"))
        connection.execute(text("INSERT INTO memberships (id) VALUES (2)"))
        new = connection.execute(text("SELECT onboarding_step, onboarding_completed_at FROM organizations WHERE id = 2")).one()
        assert new.onboarding_step == "welcome" and new.onboarding_completed_at is None
        assert connection.scalar(text("SELECT tour_completed_at FROM memberships WHERE id = 2")) is None
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM organizations")).keys() == ["id", "name"]
    engine.dispose()
