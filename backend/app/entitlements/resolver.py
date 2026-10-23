"""Read-time entitlement resolution: ``comp > subscription > trial > legacy > expired``.

Nothing here depends on a job or webhook to expire a trial, comp or grace period: ``now`` is compared on every read.
The result is cached per session (= per request) and dropped by ``invalidate`` after any mutation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.entitlements.catalog import (
    FLAG_FIELDS,
    LIMIT_FIELDS,
    TRIAL_PLAN,
    PlanDefinition,
    account_type_of,
    plan_for,
)
from app.organizations.models import Organization, OrganizationComp, Subscription

UNLIMITED = "unlimited"
SUBSCRIPTION_FULL = {"active", "trialing"}
SUBSCRIPTION_READ_ONLY = {"unpaid", "paused"}
_CACHE_KEY = "entitlement_cache"


@dataclass(frozen=True)
class Entitlements:
    organization_id: UUID | None
    account_type: str
    plan_key: str
    source: str  # comp | subscription | trial | legacy | expired
    read_only: bool
    can_have_members: bool
    max_members: int | None
    included_seats: int
    max_spaces: int | None
    active_documents: int | None
    monthly_processed_bytes: int | None
    monthly_embedding_tokens: int | None
    monthly_questions: int | None
    monthly_ocr_pages: int | None
    max_file_bytes: int | None
    max_automations: int | None
    max_api_keys: int | None
    max_data_sources: int | None
    allowed_providers: tuple[str, ...] | None
    mcp_enabled: bool
    public_api_enabled: bool
    webhooks_enabled: bool
    audit_log_retention_days: int | None
    audit_panel_enabled: bool
    sso_enabled: bool
    api_rate_limit_per_minute: int | None
    ask_rate_limit_per_minute: int | None
    trial_ends_at: datetime | None = None
    current_period_end: datetime | None = None
    comp_expires_at: datetime | None = None
    grace_ends_at: datetime | None = None
    subscription_status: str | None = None

    def monthly_limits(self) -> dict[str, int | None]:
        return {"processed_bytes": self.monthly_processed_bytes, "embedding_tokens": self.monthly_embedding_tokens,
                "questions": self.monthly_questions, "ocr_pages": self.monthly_ocr_pages}

    def provider_allowed(self, provider: str) -> bool:
        return self.allowed_providers is None or provider in self.allowed_providers

    def summary(self) -> dict[str, object]:
        """Lean block for ``GET /organizations``: just what the UI needs to gate screens."""
        return {
            "can_have_members": self.can_have_members, "max_members": self.max_members, "max_spaces": self.max_spaces,
            "max_automations": self.max_automations, "max_api_keys": self.max_api_keys,
            "max_data_sources": self.max_data_sources, "mcp_enabled": self.mcp_enabled,
            "public_api_enabled": self.public_api_enabled, "webhooks_enabled": self.webhooks_enabled,
            "audit_panel_enabled": self.audit_panel_enabled, "sso_enabled": self.sso_enabled,
            "allowed_providers": list(self.allowed_providers) if self.allowed_providers is not None else None,
        }

    def full(self) -> dict[str, object]:
        data = asdict(self)
        for key in ("organization_id", "trial_ends_at", "current_period_end", "comp_expires_at", "grace_ends_at"):
            value = data[key]
            data[key] = value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)
        data["allowed_providers"] = list(self.allowed_providers) if self.allowed_providers is not None else None
        return data


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _from_plan(plan: PlanDefinition, *, organization_id: UUID | None, account_type: str, source: str, **extra) -> Entitlements:
    if "max_members" in extra:
        max_members = extra.pop("max_members")
    elif plan.max_seats is None:
        max_members = None
    else:
        max_members = plan.included_seats if plan.can_have_members else 1
    return Entitlements(
        organization_id=organization_id, account_type=account_type, plan_key=plan.plan_key, source=source,
        read_only=extra.pop("read_only", plan.read_only), can_have_members=plan.can_have_members,
        max_members=max_members,
        included_seats=plan.included_seats, max_spaces=plan.max_spaces, active_documents=plan.active_documents,
        monthly_processed_bytes=plan.monthly_processed_bytes, monthly_embedding_tokens=plan.monthly_embedding_tokens,
        monthly_questions=plan.monthly_questions, monthly_ocr_pages=plan.monthly_ocr_pages,
        max_file_bytes=plan.max_file_bytes, max_automations=plan.max_automations, max_api_keys=plan.max_api_keys,
        max_data_sources=plan.max_data_sources, allowed_providers=plan.allowed_providers,
        mcp_enabled=plan.mcp_enabled, public_api_enabled=plan.public_api_enabled,
        webhooks_enabled=plan.webhooks_enabled, audit_log_retention_days=plan.audit_log_retention_days,
        audit_panel_enabled=plan.audit_panel_enabled, sso_enabled=plan.sso_enabled,
        api_rate_limit_per_minute=plan.api_rate_limit_per_minute,
        ask_rate_limit_per_minute=plan.ask_rate_limit_per_minute, **extra,
    )


def validate_limits_override(override: dict | None) -> dict[str, object]:
    """Only known fields; ``"unlimited"`` (or null) means no cap. Raises ``ValueError`` otherwise."""
    clean: dict[str, object] = {}
    for key, value in (override or {}).items():
        if key in LIMIT_FIELDS:
            if value in (UNLIMITED, None):
                clean[key] = None
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                clean[key] = value
            else:
                raise ValueError(f"invalid value for {key}")
        elif key in FLAG_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"invalid value for {key}")
            clean[key] = value
        else:
            raise ValueError(f"unknown limit {key}")
    return clean


def _comp_is_live(comp: OrganizationComp, now: datetime) -> bool:
    expires = _aware(comp.expires_at)
    return comp.revoked_at is None and (expires is None or expires > now)


def active_comp(session: Session, organization_id: UUID, now: datetime) -> OrganizationComp | None:
    comp = session.scalar(
        select(OrganizationComp).where(
            OrganizationComp.organization_id == organization_id, OrganizationComp.revoked_at.is_(None)
        )
    )
    return comp if comp is not None and _comp_is_live(comp, now) else None


def current_subscription(session: Session, organization_id: UUID) -> Subscription | None:
    rows = list(session.scalars(
        select(Subscription).where(Subscription.organization_id == organization_id)
        .order_by(Subscription.created_at.desc(), Subscription.id)
    ))
    live = [row for row in rows if row.status not in {"canceled", "incomplete_expired"}]
    return (live or [None])[0]


def resolve_entitlement(
    session: Session, org: Organization, now: datetime | None = None, settings: Settings | None = None
) -> Entitlements:
    from app.audit_usage.service import _settings

    now = now or datetime.now(UTC)
    settings = _settings(settings) if settings is None else settings
    base = {"organization_id": org.id, "account_type": org.account_type}

    comp = active_comp(session, org.id, now)
    if comp is not None and account_type_of(comp.plan_key) == org.account_type:
        plan = plan_for(comp.plan_key, settings)
        ent = _from_plan(plan, source="comp", comp_expires_at=_aware(comp.expires_at),
                         trial_ends_at=_aware(org.trial_ends_at), **base)
        return _apply_override(ent, comp.limits_override)

    sub = current_subscription(session, org.id)
    if sub is not None and sub.status != "incomplete" and account_type_of(sub.plan_key) == org.account_type:
        access = _subscription_access(sub, now, settings)
        if access is not None:
            plan = plan_for(sub.plan_key, settings)
            seats = max(plan.included_seats, min(sub.seats, plan.max_seats or sub.seats))
            return _from_plan(
                plan, source="subscription", read_only=access["read_only"], max_members=seats,
                current_period_end=_aware(sub.current_period_end), grace_ends_at=access["grace_ends_at"],
                subscription_status=sub.status, trial_ends_at=_aware(org.trial_ends_at), **base)

    trial_end = _aware(org.trial_ends_at)
    if trial_end is not None and trial_end > now:
        plan = plan_for(TRIAL_PLAN[org.account_type], settings)
        return _from_plan(plan, source="trial", trial_ends_at=trial_end, **base)

    if org.entitlement_source == "legacy":
        return _from_plan(plan_for("legacy", settings), source="legacy", max_members=None, **base)

    return _from_plan(plan_for("expired", settings), source="expired", trial_ends_at=trial_end,
                      **base)


def _subscription_access(sub: Subscription, now: datetime, settings: Settings) -> dict[str, object] | None:
    end = _aware(sub.current_period_end)
    if sub.cancel_at_period_end and end is not None and end <= now:
        return None
    cancel_at = _aware(sub.cancel_at)
    if cancel_at is not None and cancel_at <= now:
        return None
    if sub.status in SUBSCRIPTION_FULL:
        return {"read_only": False, "grace_ends_at": None}
    if sub.status == "past_due":
        since = _aware(sub.past_due_since) or now
        grace_end = since + timedelta(days=getattr(settings, "past_due_grace_days", 7))
        return {"read_only": grace_end <= now, "grace_ends_at": grace_end}
    if sub.status in SUBSCRIPTION_READ_ONLY:
        return {"read_only": True, "grace_ends_at": None}
    return None


def _apply_override(ent: Entitlements, override: dict | None) -> Entitlements:
    if not override:
        return ent
    try:
        clean = validate_limits_override(override)
    except ValueError:
        return ent
    changes = dict(clean)
    if "max_members" in clean and clean["max_members"] != 1:
        changes["can_have_members"] = ent.account_type == "business"
    return replace(ent, **changes)


def entitlements_for(session: Session, organization_id: UUID, settings: Settings | None = None) -> Entitlements:
    """Per-request cache (keyed on the session). Unknown organization => treated as an expired, read-only one."""
    cache: dict = session.info.setdefault(_CACHE_KEY, {})
    if organization_id in cache:
        return cache[organization_id]
    org = session.get(Organization, organization_id)
    if org is None:  # no row to restrict (the FK/permission layers reject unknown organizations): behave as before
        from app.audit_usage.service import _settings
        return _from_plan(plan_for("legacy", _settings(settings)), organization_id=organization_id,
                          account_type="business", source="legacy", max_members=None)
    ent = resolve_entitlement(session, org, settings=settings)
    cache[organization_id] = ent
    return ent


def invalidate(session: Session, organization_id: UUID | None = None) -> None:
    cache = session.info.get(_CACHE_KEY)
    if cache is None:
        return
    if organization_id is None:
        cache.clear()
    else:
        cache.pop(organization_id, None)


def project(session: Session, org: Organization, settings: Settings | None = None) -> Entitlements:
    """Refresh the ``plan_key``/``entitlement_source`` projection columns from the resolved entitlement.

    ``legacy`` is also an input marker: it is only cleared by a subscription (first voluntary purchase)."""
    invalidate(session, org.id)
    ent = resolve_entitlement(session, org, settings=settings)
    if org.entitlement_source == "legacy" and ent.source != "subscription":
        pass
    else:
        org.plan_key, org.entitlement_source = ent.plan_key, ent.source
    session.info.setdefault(_CACHE_KEY, {})[org.id] = ent
    return ent

