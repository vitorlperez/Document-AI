"""Operator CLI: promote a user to platform admin and manage courtesy plans (comps).

    python scripts/platform_admin.py grant-staff --email you@example.com [--role support]
    python scripts/platform_admin.py comp grant --org <uuid> --plan business_team --reason "pilot" --days 30 --by you@example.com
    python scripts/platform_admin.py comp revoke --org <uuid> --comp <uuid> --by you@example.com
    python scripts/platform_admin.py comp list --org <uuid>

Everything goes through the same services (and AuditLog) as the HTTP endpoints.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory
from app.entitlements.comps import CompService, serialize_comp
from app.identity.models import User
from app.organizations.models import PlatformStaff


def _user(session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise SystemExit(f"user not found: {email}")
    return user


def grant_staff(session, *, email: str, role: str = "admin") -> PlatformStaff:
    """Idempotent: creates the PlatformStaff row or re-activates it with the requested role."""
    if role not in {"admin", "support"}:
        raise SystemExit("role must be admin or support")
    user = _user(session, email)
    staff = session.scalar(select(PlatformStaff).where(PlatformStaff.user_id == user.id))
    if staff is None:
        staff = PlatformStaff(user_id=user.id)
        session.add(staff)
    staff.is_active, staff.role = True, role
    session.flush()
    return staff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    staff = sub.add_parser("grant-staff")
    staff.add_argument("--email", required=True)
    staff.add_argument("--role", default="admin", choices=["admin", "support"])
    comp = sub.add_parser("comp")
    comp_sub = comp.add_subparsers(dest="action", required=True)
    grant = comp_sub.add_parser("grant")
    grant.add_argument("--org", required=True)
    grant.add_argument("--plan", required=True)
    grant.add_argument("--reason", required=True)
    grant.add_argument("--by", required=True, help="e-mail of the platform admin recorded as the grantor")
    grant.add_argument("--days", type=int)
    grant.add_argument("--no-expiry", action="store_true")
    revoke = comp_sub.add_parser("revoke")
    revoke.add_argument("--org", required=True)
    revoke.add_argument("--comp", required=True)
    revoke.add_argument("--by", required=True)
    listing = comp_sub.add_parser("list")
    listing.add_argument("--org", required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    factory = build_session_factory(build_engine(settings))
    with factory.begin() as session:
        if args.command == "grant-staff":
            row = grant_staff(session, email=args.email, role=args.role)
            print(f"platform staff {args.email} role={row.role} active")
            return 0
        service = CompService(session, settings)
        organization_id = UUID(args.org)
        if args.action == "list":
            for item in service.list_for(organization_id):
                print(serialize_comp(item))
            return 0
        actor = _user(session, args.by)
        from app.entitlements.comps import require_platform_admin

        require_platform_admin(session, actor.id)
        if args.action == "grant":
            expires = datetime.now(UTC) + timedelta(days=args.days) if args.days else None
            created, has_subscription = service.grant(
                organization_id=organization_id, actor_user_id=actor.id, plan_key=args.plan, reason=args.reason,
                expires_at=expires, permanent=args.no_expiry)
            print(serialize_comp(created))
            if has_subscription:
                print("WARNING: organization still has an active paid subscription; cancel/refund it separately.")
        else:
            service.revoke(organization_id=organization_id, comp_id=UUID(args.comp), actor_user_id=actor.id)
            print("revoked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
