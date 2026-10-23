"""Single source of truth for plan limits and list prices (BRL, integer cents).

``legacy`` is built from ``Settings`` so organizations that predate account types keep today's numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.core.config import Settings

PERSONAL, BUSINESS = "personal", "business"
SELLABLE_PLANS = ("personal_basic", "personal_pro", "business_team", "business_scale")
TRIAL_PLAN = {PERSONAL: "personal_trial", BUSINESS: "business_trial"}
ALL_PROVIDERS: tuple[str, ...] | None = None  # None == every provider
MB, GB = 1_000_000, 1_000_000_000

# Limit fields that a comp's ``limits_override`` may set. ``None`` means unlimited.
LIMIT_FIELDS = (
    "max_members", "max_spaces", "active_documents", "monthly_processed_bytes", "monthly_embedding_tokens",
    "monthly_questions", "monthly_ocr_pages", "max_file_bytes", "max_automations", "max_api_keys",
    "max_data_sources", "audit_log_retention_days", "api_rate_limit_per_minute", "ask_rate_limit_per_minute",
)
FLAG_FIELDS = ("mcp_enabled", "public_api_enabled", "webhooks_enabled", "sso_enabled", "audit_panel_enabled")


@dataclass(frozen=True)
class PlanDefinition:
    plan_key: str
    account_type: str
    title: str
    sellable: bool = True
    can_have_members: bool = False
    included_seats: int = 1
    max_seats: int | None = 1  # None == unlimited (legacy)
    max_spaces: int | None = 1
    active_documents: int | None = 500
    monthly_processed_bytes: int | None = 2 * GB
    monthly_embedding_tokens: int | None = 2_000_000
    monthly_questions: int | None = 200
    monthly_ocr_pages: int | None = 400
    max_file_bytes: int | None = 25 * MB
    max_automations: int | None = 3
    max_api_keys: int | None = 0
    max_data_sources: int | None = 2
    allowed_providers: tuple[str, ...] | None = ("google_drive", "google_drive_sa")
    mcp_enabled: bool = False
    public_api_enabled: bool = False
    webhooks_enabled: bool = False
    audit_log_retention_days: int | None = 30
    audit_panel_enabled: bool = False
    sso_enabled: bool = False
    api_rate_limit_per_minute: int | None = 60
    ask_rate_limit_per_minute: int | None = 5
    read_only: bool = False
    # list prices (cents BRL); ``extra_seat_*`` only for business plans
    price_month_cents: int | None = None
    price_year_cents: int | None = None
    extra_seat_month_cents: int | None = None
    extra_seat_year_cents: int | None = None
    highlights: tuple[str, ...] = field(default_factory=tuple)


_PERSONAL_BASIC = PlanDefinition(
    plan_key="personal_basic", account_type=PERSONAL, title="Pessoal Básico",
    price_month_cents=3_900, price_year_cents=39_000,
)
_PERSONAL_PRO = PlanDefinition(
    plan_key="personal_pro", account_type=PERSONAL, title="Pessoal Pro",
    max_spaces=3, active_documents=2_000, monthly_processed_bytes=6 * GB, monthly_embedding_tokens=6_000_000,
    monthly_questions=600, monthly_ocr_pages=1_200, max_file_bytes=50 * MB, max_automations=10, max_api_keys=1,
    max_data_sources=5, allowed_providers=("google_drive", "google_drive_sa", "onedrive", "notion"), mcp_enabled=True,
    public_api_enabled=True, webhooks_enabled=True, api_rate_limit_per_minute=120, ask_rate_limit_per_minute=10,
    price_month_cents=9_900, price_year_cents=99_000,
)
_BUSINESS_TEAM = PlanDefinition(
    plan_key="business_team", account_type=BUSINESS, title="Empresa Team", can_have_members=True,
    included_seats=5, max_seats=15, max_spaces=25, active_documents=3_000, monthly_processed_bytes=12 * GB,
    monthly_embedding_tokens=10_000_000, monthly_questions=1_000, monthly_ocr_pages=2_000, max_file_bytes=100 * MB,
    max_automations=20, max_api_keys=10, max_data_sources=10, allowed_providers=ALL_PROVIDERS, mcp_enabled=True,
    public_api_enabled=True, webhooks_enabled=True, audit_log_retention_days=180, audit_panel_enabled=True,
    api_rate_limit_per_minute=600, ask_rate_limit_per_minute=10,
    price_month_cents=29_900, price_year_cents=299_000, extra_seat_month_cents=4_900, extra_seat_year_cents=49_000,
)
_BUSINESS_SCALE = replace(
    _BUSINESS_TEAM, plan_key="business_scale", title="Empresa Scale", included_seats=20, max_seats=100,
    max_spaces=200, active_documents=20_000, monthly_processed_bytes=100 * GB, monthly_embedding_tokens=50_000_000,
    monthly_questions=5_000, monthly_ocr_pages=10_000, max_automations=100, max_api_keys=50, max_data_sources=30,
    audit_log_retention_days=365, sso_enabled=True, api_rate_limit_per_minute=1_200, ask_rate_limit_per_minute=30,
    price_month_cents=89_900, price_year_cents=899_000, extra_seat_month_cents=3_900, extra_seat_year_cents=39_000,
)
_PERSONAL_TRIAL = replace(
    _PERSONAL_BASIC, plan_key="personal_trial", title="Teste Pessoal", sellable=False, max_spaces=1,
    active_documents=300, monthly_processed_bytes=1 * GB, monthly_embedding_tokens=1_000_000, monthly_questions=100,
    monthly_ocr_pages=200, max_automations=1, max_api_keys=0, max_data_sources=2, price_month_cents=None,
    price_year_cents=None,
)
_BUSINESS_TRIAL = replace(
    _BUSINESS_TEAM, plan_key="business_trial", title="Teste Empresa", sellable=False, max_seats=5, max_spaces=5,
    active_documents=1_000, monthly_processed_bytes=3 * GB, monthly_embedding_tokens=3_000_000, monthly_questions=300,
    monthly_ocr_pages=600, max_automations=20, max_api_keys=3, max_data_sources=3, audit_log_retention_days=30, price_month_cents=None, price_year_cents=None,
    extra_seat_month_cents=None, extra_seat_year_cents=None,
)
_EXPIRED = PlanDefinition(
    plan_key="expired", account_type=BUSINESS, title="Expirado", sellable=False, read_only=True, can_have_members=False,
    max_seats=None, max_spaces=None, active_documents=None, max_automations=0, max_api_keys=0, max_data_sources=0,
)

_STATIC = {
    plan.plan_key: plan
    for plan in (_PERSONAL_BASIC, _PERSONAL_PRO, _BUSINESS_TEAM, _BUSINESS_SCALE, _PERSONAL_TRIAL, _BUSINESS_TRIAL, _EXPIRED)
}


def legacy_plan(settings: Settings) -> PlanDefinition:
    """Exactly today's global numbers: members allowed, no seat ceiling, no read-only."""

    def g(name: str):  # tolerate partial settings objects (bare unit use): fall back to the field default
        return getattr(settings, name, Settings.model_fields[name].default)

    return PlanDefinition(
        plan_key="legacy", account_type=BUSINESS, title="Plano legado", sellable=False, can_have_members=True,
        included_seats=1, max_seats=None, max_spaces=None, active_documents=g("active_document_limit"),
        monthly_processed_bytes=g("monthly_limit_processed_bytes"),
        monthly_embedding_tokens=g("monthly_limit_embedding_tokens"),
        monthly_questions=g("monthly_limit_questions"), monthly_ocr_pages=g("monthly_limit_ocr_pages"),
        max_file_bytes=g("max_file_bytes"), max_automations=20, max_api_keys=None, max_data_sources=None,
        allowed_providers=ALL_PROVIDERS, mcp_enabled=True, public_api_enabled=True, webhooks_enabled=True,
        audit_log_retention_days=None, audit_panel_enabled=True, sso_enabled=False,
        api_rate_limit_per_minute=g("api_org_rate_limit_per_minute"),
        ask_rate_limit_per_minute=g("api_ask_rate_limit_per_minute"),
    )


def plan_for(plan_key: str, settings: Settings) -> PlanDefinition:
    if plan_key == "legacy":
        return legacy_plan(settings)
    try:
        return _STATIC[plan_key]
    except KeyError as error:
        raise KeyError(f"unknown plan {plan_key}") from error


def sellable_plans() -> list[PlanDefinition]:
    return [_STATIC[key] for key in SELLABLE_PLANS]


def is_sellable(plan_key: str) -> bool:
    return plan_key in SELLABLE_PLANS


def account_type_of(plan_key: str) -> str:
    return _STATIC[plan_key].account_type if plan_key in _STATIC else BUSINESS


def default_upgrade_target(current_plan_key: str, account_type: str) -> str | None:
    """Where an error should point the user: the next sensible plan, if any."""
    ladder = {"personal_trial": "personal_basic", "personal_basic": "personal_pro", "personal_pro": "business_team",
              "business_trial": "business_team", "business_team": "business_scale", "expired": None}
    if account_type == PERSONAL and current_plan_key not in ladder:
        return "personal_basic"
    return ladder.get(current_plan_key, "business_team" if account_type == PERSONAL else None)


def seat_price_cents(plan: PlanDefinition, seats: int, interval: str) -> int | None:
    """Total for ``seats`` seats under the base+extra model; ``None`` for plans that are not sold."""
    base = plan.price_year_cents if interval == "year" else plan.price_month_cents
    if base is None:
        return None
    extra = plan.extra_seat_year_cents if interval == "year" else plan.extra_seat_month_cents
    return base + max(0, seats - plan.included_seats) * (extra or 0)
