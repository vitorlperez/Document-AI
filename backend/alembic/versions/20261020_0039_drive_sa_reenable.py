"""Drive robots: one *active* robot per organization, many retired ones (decision 2026-10-20).

A retired robot stays a permanent record and never returns to the pool; the organization can reconnect and receive a
NEW robot. ``UNIQUE(organization_id)`` becomes a partial unique index on ``status = 'assigned'`` and the trigger keeps
forbidding every recycling path.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_0039"
down_revision = "20261020_0038"
branch_labels = None
depends_on = None

OLD_UNIQUE = "google_sa_identities_organization_id_key"
ACTIVE_INDEX = "uq_google_sa_identities_org_assigned"

TRIGGER_V2 = """CREATE OR REPLACE FUNCTION google_sa_preserve_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.organization_id IS NOT NULL AND NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
        RAISE EXCEPTION 'robot assignment is permanent';
      END IF;
      IF OLD.status IN ('retired','compromised') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'robot retirement is permanent';
      END IF;
      IF OLD.status <> 'free' AND NEW.status = 'free' THEN
        RAISE EXCEPTION 'robot cannot return to the pool';
      END IF;
      RETURN NEW;
    END $$"""

TRIGGER_V1 = """CREATE OR REPLACE FUNCTION google_sa_preserve_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (OLD.organization_id IS NOT NULL AND NEW.organization_id IS DISTINCT FROM OLD.organization_id)
         OR (OLD.status IN ('retired','compromised') AND NEW.status IS DISTINCT FROM OLD.status) THEN
        RAISE EXCEPTION 'robot assignment is permanent';
      END IF;
      RETURN NEW;
    END $$"""


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.drop_constraint(OLD_UNIQUE, "google_sa_identities", type_="unique")
    else:
        with op.batch_alter_table("google_sa_identities") as batch:
            batch.drop_constraint(OLD_UNIQUE, type_="unique")
    op.create_index(
        ACTIVE_INDEX,
        "google_sa_identities",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status = 'assigned'"),
        sqlite_where=sa.text("status = 'assigned'"),
    )
    if postgres:
        op.execute(TRIGGER_V2)


def downgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if not context_is_offline():
        extra = bind.execute(
            sa.text(
                "SELECT count(*) FROM (SELECT organization_id FROM google_sa_identities "
                "WHERE organization_id IS NOT NULL GROUP BY organization_id HAVING count(*) > 1) t"
            )
        ).scalar()
        if extra:
            raise RuntimeError(
                "cannot downgrade: some organizations have more than one robot identity (re-enabled after retirement)"
            )
    op.drop_index(ACTIVE_INDEX, table_name="google_sa_identities")
    if postgres:
        op.create_unique_constraint(OLD_UNIQUE, "google_sa_identities", ["organization_id"])
        op.execute(TRIGGER_V1)
    else:
        with op.batch_alter_table("google_sa_identities") as batch:
            batch.create_unique_constraint(OLD_UNIQUE, ["organization_id"])


def context_is_offline():
    return op.get_context().as_sql
