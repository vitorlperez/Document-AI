"""Guards (called inside services, so jobs/MCP/public API obey them too) and the account-type transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.models import ApiKey
from app.audit_usage.models import AuditLog
from app.automations.models import Automation
from app.core.config import Settings
from app.entitlements.catalog import (
    BUSINESS,
    PERSONAL,
    TRIAL_PLAN,
    account_type_of,
    default_upgrade_target,
    is_sellable,
    plan_for,
)
from app.entitlements.errors import AccountTypeError, EntitlementError
from app.entitlements.resolver import (
    Entitlements,
    active_comp,
    current_subscription,
    entitlements_for,
    invalidate,
    project,
)
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipInvitation, MembershipRole, Organization
from app.spaces.models import Space


def _upgrade_to(ent: Entitlements) -> str | None:
    return default_upgrade_target(ent.plan_key, ent.account_type)


def lock_organization(session: Session, organization_id: UUID) -> Organization:
    org = session.scalar(select(Organization).where(Organization.id == organization_id).with_for_update())
    if org is None:
        raise EntitlementError("organization_not_found", status_code=404)
    return org


def _lock_if_present(session: Session, organization_id: UUID) -> None:
    session.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())


def require_writable(ent: Entitlements) -> None:
    if ent.read_only:
        code = "trial_expired" if ent.source == "expired" and ent.trial_ends_at is not None else "read_only"
        raise EntitlementError(code, "organization is read-only until a plan is active", upgrade_to=_upgrade_to(ent))


def active_member_count(session: Session, organization_id: UUID) -> int:
    return session.scalar(select(func.count()).select_from(Membership).where(
        Membership.organization_id == organization_id, Membership.is_active.is_(True))) or 0


def pending_invitation_count(session: Session, organization_id: UUID, *, except_email: str | None = None) -> int:
    statement = select(func.count()).select_from(MembershipInvitation).where(
        MembershipInvitation.organization_id == organization_id, MembershipInvitation.accepted_at.is_(None),
        MembershipInvitation.revoked_at.is_(None), MembershipInvitation.expires_at > datetime.now(UTC))
    if except_email is not None:
        statement = statement.where(MembershipInvitation.email != except_email)
    return session.scalar(statement) or 0


def require_can_invite(session: Session, organization_id: UUID, *, except_email: str | None = None) -> Entitlements:
    """Invitation guard: writable, members allowed, and ``active members + pending invitations`` below the seat cap."""
    _lock_if_present(session, organization_id)
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    _require_members_allowed(ent)
    used = active_member_count(session, organization_id) + pending_invitation_count(
        session, organization_id, except_email=except_email)
    _check_seats(ent, used)
    return ent


def require_seat_available(session: Session, organization_id: UUID) -> Entitlements:
    """Accept/add guard: only people who are already members count (the invitation being accepted is not one)."""
    _lock_if_present(session, organization_id)
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    _require_members_allowed(ent)
    _check_seats(ent, active_member_count(session, organization_id))
    return ent


def _require_members_allowed(ent: Entitlements) -> None:
    if not ent.can_have_members:
        raise AccountTypeError(
            "personal_no_members", "personal accounts are single-user; upgrade to a business account to add people",
            limit=1, upgrade_to="business_team")


def _check_seats(ent: Entitlements, used: int) -> None:
    if ent.max_members is not None and used >= ent.max_members:
        target = "business_scale" if ent.plan_key in {"business_team", "business_trial"} else None
        raise EntitlementError("seat_limit", "no seats available", limit=ent.max_members, used=used, upgrade_to=target)


def _quota(ent: Entitlements, code: str, limit: int | None, used: int) -> None:
    if limit is not None and used >= limit:
        raise EntitlementError(code, f"{code.replace('_', ' ')}", limit=limit, used=used, upgrade_to=_upgrade_to(ent))


def require_space_quota(session: Session, organization_id: UUID) -> None:
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    used = session.scalar(select(func.count()).select_from(Space).where(
        Space.organization_id == organization_id, Space.archived_at.is_(None))) or 0
    _quota(ent, "space_limit", ent.max_spaces, used)


def require_automation_quota(session: Session, organization_id: UUID) -> None:
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    used = session.scalar(select(func.count()).select_from(Automation).where(
        Automation.organization_id == organization_id)) or 0
    if ent.max_automations is not None and used >= ent.max_automations:
        raise EntitlementError("automation_limit", "automation_limit_reached", limit=ent.max_automations, used=used,
                               upgrade_to=_upgrade_to(ent))


def require_api_key_quota(session: Session, organization_id: UUID) -> None:
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    if not ent.public_api_enabled:
        raise EntitlementError("feature_unavailable", "public API is not part of this plan", upgrade_to=_upgrade_to(ent))
    used = session.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.organization_id == organization_id, ApiKey.revoked_at.is_(None))) or 0
    _quota(ent, "api_key_limit", ent.max_api_keys, used)


def require_feature(session: Session, organization_id: UUID, feature: str) -> Entitlements:
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    if not getattr(ent, f"{feature}_enabled"):
        raise EntitlementError("feature_unavailable", f"{feature} is not part of this plan", upgrade_to=_upgrade_to(ent))
    return ent


def require_source_quota(session: Session, organization_id: UUID, provider: str) -> None:
    """Call right before creating a new ``DataSource`` (reconnecting an existing one is not a new source)."""
    ent = entitlements_for(session, organization_id)
    require_writable(ent)
    if not ent.provider_allowed(provider):
        raise EntitlementError("provider_unavailable", f"{provider} is not part of this plan", upgrade_to=_upgrade_to(ent))
    used = session.scalar(select(func.count()).select_from(DataSource).where(
        DataSource.organization_id == organization_id)) or 0
    _quota(ent, "data_source_limit", ent.max_data_sources, used)


def require_org_creation_quota(session: Session, user_id: UUID, account_type: str) -> None:
    """One personal organization per owner (anti-abuse); business organizations are not capped."""
    if account_type != PERSONAL:
        return
    owned = session.scalar(
        select(func.count()).select_from(Organization).join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id, Membership.role == MembershipRole.OWNER, Membership.is_active.is_(True),
               Organization.account_type == PERSONAL)) or 0
    if owned >= 1:
        raise AccountTypeError("personal_org_limit", "only one personal organization per user", limit=1, used=owned,
                               upgrade_to="business_team")


def trial_already_used(session: Session, user_id: UUID, account_type: str) -> bool:
    return (session.scalar(select(func.count()).select_from(Organization).where(
        Organization.created_by_user_id == user_id, Organization.account_type == account_type,
        Organization.trial_started_at.is_not(None))) or 0) > 0


def start_trial(session: Session, org: Organization, user_id: UUID, settings: Settings, now: datetime | None = None) -> None:
    """New organization: local trial (one per creator and type, otherwise the org starts expired/read-only)."""
    now = now or datetime.now(UTC)
    org.created_by_user_id = user_id
    if trial_already_used(session, user_id, org.account_type):
        org.plan_key, org.entitlement_source = "expired", "expired"
        org.trial_started_at = org.trial_ends_at = None
    else:
        org.trial_started_at, org.trial_ends_at = now, now + timedelta(days=settings.trial_days)
        org.plan_key, org.entitlement_source = TRIAL_PLAN[org.account_type], "trial"
    invalidate(session, org.id)


def _audit(session: Session, org_id: UUID, actor: UUID, action: str) -> None:
    session.add(AuditLog(organization_id=org_id, actor_user_id=actor, action=action, target_type="organization",
                         target_id=org_id))
    session.flush()


def upgrade_to_business(
    session: Session, *, organization_id: UUID, actor_user_id: UUID, name: str, plan_key: str, seats: int,
    interval: str, provider, settings: Settings,
) -> Organization:
    """Personal -> business in place (same ``organization_id``). Idempotent for an already-business org."""
    org = lock_organization(session, organization_id)
    if account_type_of(plan_key) != BUSINESS or not is_sellable(plan_key):
        raise EntitlementError("invalid_plan", "choose a business plan", status_code=422)
    plan = plan_for(plan_key, settings)
    if seats < 1 or (plan.max_seats is not None and seats > plan.max_seats):
        raise EntitlementError("invalid_seats", "seat count outside the plan range", limit=plan.max_seats, status_code=422)
    if org.account_type == BUSINESS:
        return org
    comp = active_comp(session, org.id, datetime.now(UTC))
    if comp is not None and account_type_of(comp.plan_key) != BUSINESS:
        raise EntitlementError("comp_type_mismatch", "revoke the personal courtesy plan before upgrading", status_code=409)
    sub = current_subscription(session, org.id)
    if sub is not None and sub.status in {"active", "trialing", "past_due"}:
        provider.change_plan(subscription=sub, plan_key=plan_key, interval=interval, seats=seats)
        sub.plan_key, sub.seats, sub.interval = plan_key, seats, interval
    org.account_type, org.name = BUSINESS, name.strip()
    org.account_type_changed_at = datetime.now(UTC)
    _audit(session, org.id, actor_user_id, "organization.upgraded")
    project(session, org, settings)
    return org


def downgrade_to_personal(
    session: Session, *, organization_id: UUID, actor_user_id: UUID, plan_key: str | None, provider, settings: Settings,
) -> Organization:
    org = lock_organization(session, organization_id)
    if org.account_type == PERSONAL:
        return org
    blockers: list[str] = []
    members = active_member_count(session, org.id)
    if members > 1:
        blockers.append("members")
    if pending_invitation_count(session, org.id) > 0:
        blockers.append("pending_invitations")
    changed = org.account_type_changed_at
    if changed is not None:
        changed = changed.replace(tzinfo=UTC) if changed.tzinfo is None else changed
        if changed + timedelta(days=settings.account_downgrade_cooldown_days) > datetime.now(UTC):
            blockers.append("cooldown")
    if blockers:
        error = EntitlementError("downgrade_blocked", "downgrade is not allowed yet", used=members, status_code=409)
        error.blockers = blockers  # type: ignore[attr-defined]
        raise error
    sub = current_subscription(session, org.id)
    target = plan_key or "personal_basic"
    if account_type_of(target) != PERSONAL or not is_sellable(target):
        raise EntitlementError("invalid_plan", "choose a personal plan", status_code=422)
    if sub is not None and sub.status in {"active", "trialing", "past_due"}:
        provider.change_plan(subscription=sub, plan_key=target, interval=sub.interval, seats=1)
        sub.plan_key, sub.seats = target, 1
    org.account_type = PERSONAL
    org.account_type_changed_at = datetime.now(UTC)
    invalidate(session, org.id)
    paused = _pause_excess_automations(session, org, settings)
    _audit(session, org.id, actor_user_id, "organization.downgraded")
    project(session, org, settings)
    org._paused_automations = paused  # type: ignore[attr-defined]
    return org


def _pause_excess_automations(session: Session, org: Organization, settings: Settings) -> int:
    """Never delete: automations above the new ceiling are only disabled (oldest stay enabled)."""
    ent = entitlements_for(session, org.id, settings)
    if ent.max_automations is None:
        return 0
    enabled = list(session.scalars(select(Automation).where(
        Automation.organization_id == org.id, Automation.enabled.is_(True)).order_by(Automation.created_at, Automation.id)))
    excess = enabled[ent.max_automations:]
    for automation in excess:
        automation.enabled = False
    session.flush()
    return len(excess)
