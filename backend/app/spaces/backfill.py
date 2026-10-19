"""Idempotent first-run data for Spaces: one default Space per organization with everyone and everything.

Uses lightweight table definitions (not the ORM models, not reflection) so the migration keeps working
after the application models evolve.
"""

from uuid import uuid4

import sqlalchemy as sa

MIGRATION_DISCLOSURE = {"text_version": "backfill", "acknowledged_at": None, "origin": "migration"}

_meta = sa.MetaData()
_organizations = sa.Table(
    "organizations", _meta, sa.Column("id", sa.Uuid, primary_key=True), sa.Column("spaces_resolver_mode", sa.String)
)
_memberships = sa.Table(
    "memberships", _meta,
    sa.Column("organization_id", sa.Uuid), sa.Column("user_id", sa.Uuid),
    sa.Column("role", sa.String), sa.Column("is_active", sa.Boolean),
)
_folders = sa.Table(
    "workspace_folders", _meta, sa.Column("id", sa.Uuid, primary_key=True), sa.Column("organization_id", sa.Uuid)
)
_spaces = sa.Table(
    "spaces", _meta,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("organization_id", sa.Uuid),
    sa.Column("name", sa.String), sa.Column("name_key", sa.String), sa.Column("description", sa.String),
    sa.Column("is_default", sa.Boolean),
)
_members = sa.Table(
    "space_members", _meta,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("organization_id", sa.Uuid),
    sa.Column("space_id", sa.Uuid), sa.Column("user_id", sa.Uuid), sa.Column("role", sa.String),
)
_grants = sa.Table(
    "space_folder_grants", _meta,
    sa.Column("id", sa.Uuid, primary_key=True), sa.Column("organization_id", sa.Uuid),
    sa.Column("space_id", sa.Uuid), sa.Column("workspace_folder_id", sa.Uuid), sa.Column("disclosure", sa.JSON),
)


def backfill_default_spaces(connection: sa.Connection) -> int:
    """Create "Geral" for every organization that has no Space yet. Returns how many were filled."""
    has_space = sa.exists().where(_spaces.c.organization_id == _organizations.c.id)
    pending = connection.execute(sa.select(_organizations.c.id).where(~has_space)).scalars().all()
    for organization_id in pending:
        space_id = uuid4()
        connection.execute(_spaces.insert().values(
            id=space_id, organization_id=organization_id, name="Geral", name_key="geral", is_default=True,
            description="Espaço inicial — todos os membros e todas as pastas"))
        member_rows = connection.execute(sa.select(_memberships.c.user_id, _memberships.c.role).where(
            _memberships.c.organization_id == organization_id, _memberships.c.is_active.is_(True))).all()
        for user_id, role in member_rows:
            connection.execute(_members.insert().values(
                id=uuid4(), organization_id=organization_id, space_id=space_id, user_id=user_id,
                role="manager" if str(getattr(role, "value", role)).lower() in ("owner", "admin") else "member"))
        folder_ids = connection.execute(
            sa.select(_folders.c.id).where(_folders.c.organization_id == organization_id)).scalars().all()
        for folder_id in folder_ids:
            connection.execute(_grants.insert().values(
                id=uuid4(), organization_id=organization_id, space_id=space_id, workspace_folder_id=folder_id,
                disclosure={**MIGRATION_DISCLOSURE, "member_count": len(member_rows)}))
        connection.execute(
            _organizations.update().where(_organizations.c.id == organization_id).values(spaces_resolver_mode="shadow"))
    return len(pending)
