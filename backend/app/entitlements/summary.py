"""Shared JSON shape for an organization's plan state (``GET /organizations``, ``/me``, billing)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.entitlements.resolver import Entitlements, entitlements_for
from app.organizations.models import Organization


def plan_state(ent: Entitlements) -> dict[str, object]:
    return {
        "account_type": ent.account_type, "plan_key": ent.plan_key, "entitlement_source": ent.source,
        "trial_ends_at": ent.trial_ends_at.isoformat() if ent.trial_ends_at else None, "read_only": ent.read_only,
        "entitlements": ent.summary(),
    }


def organization_plan_state(session: Session, org: Organization, settings: Settings | None = None) -> dict[str, object]:
    return plan_state(entitlements_for(session, org.id, settings))
