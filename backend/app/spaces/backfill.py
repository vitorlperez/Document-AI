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
    """Create or complete "Geral" for every organization. Returns how many organizations changed.

    Safe to re-run (also after ``downgrade -1`` + ``upgrade``): an organization without any Space gets "Geral"
    with everyone and every folder; one that already has its default Space only gets what is missing — active
    members not in it (a member who left on purpose is not resurrected) and folders no Space has ever granted.
    Organizations that manage their own Spaces (no default Space) are left alone. Rows go in one batch per table.
    """
    changed = 0
    for organization_id in connection.execute(sa.select(_organizations.c.id)).scalars().all():
        default_id = connection.execute(sa.select(_spaces.c.id).where(
            _spaces.c.organization_id == organization_id, _spaces.c.is_default.is_(True)).limit(1)).scalar()
        created = default_id is None
        if created:
            if connection.execute(sa.select(_spaces.c.id).where(
                    _spaces.c.organization_id == organization_id).limit(1)).first() is not None:
                continue
            default_id = uuid4()
            connection.execute(_spaces.insert().values(
                id=default_id, organization_id=organization_id, name="Geral", name_key="geral", is_default=True,
                description="Espaço inicial — todos os membros e todas as pastas"))
        in_space = sa.exists().where(_members.c.space_id == default_id, _members.c.user_id == _memberships.c.user_id)
        member_rows = connection.execute(sa.select(_memberships.c.user_id, _memberships.c.role).where(
            _memberships.c.organization_id == organization_id, _memberships.c.is_active.is_(True),
            ~in_space)).all()
        if member_rows:
            connection.execute(_members.insert(), [
                {"id": uuid4(), "organization_id": organization_id, "space_id": default_id, "user_id": user_id,
                 "role": "manager" if str(getattr(role, "value", role)).lower() in ("owner", "admin") else "member"}
                for user_id, role in member_rows])
        ever_granted = sa.exists().where(_grants.c.workspace_folder_id == _folders.c.id)
        folder_ids = connection.execute(sa.select(_folders.c.id).where(
            _folders.c.organization_id == organization_id, ~ever_granted)).scalars().all()
        if folder_ids:
            active_members = connection.execute(sa.select(sa.func.count()).select_from(_members).where(
                _members.c.space_id == default_id)).scalar()
            connection.execute(_grants.insert(), [
                {"id": uuid4(), "organization_id": organization_id, "space_id": default_id,
                 "workspace_folder_id": folder_id,
                 "disclosure": {**MIGRATION_DISCLOSURE, "member_count": active_members}}
                for folder_id in folder_ids])
        if created:
            connection.execute(_organizations.update().where(_organizations.c.id == organization_id).values(
                spaces_resolver_mode="shadow"))
        changed += bool(created or member_rows or folder_ids)
    return changed
