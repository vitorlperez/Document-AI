"""Stripe view of the plan catalog: pure data derived from ``app.entitlements.catalog`` (no ``stripe`` import).

``catalog.py`` stays the single source of truth for prices and limits. This module only describes how each sellable
plan is modelled in Stripe so the sync script (``scripts/stripe_sync_catalog.py``) and the provider agree:

* one Product per plan, with a stable ID (``arquivio_<plan_key>``) and ``metadata.plan_key``/``account_type``;
* two recurring Prices per Product (month/year) with lookup keys ``<plan_key>_monthly``/``<plan_key>_yearly``;
* personal plans: flat per-unit Price, quantity 1;
* business plans: ONE graduated tiered Price, quantity = seats. Tier 1 covers ``included_seats`` with a flat amount
  equal to the base price (unit amount 0); tier 2 charges the extra-seat price per seat beyond that.

Plans are identified from ``price.metadata.plan_key`` (fallback ``product.metadata.plan_key``), never the lookup key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.entitlements.catalog import PlanDefinition, sellable_plans

CURRENCY = "brl"
INTERVALS = ("month", "year")
MANAGED_BY = "arquivio_catalog_sync"
PRODUCT_ID_PREFIX = "arquivio_"
_LOOKUP_SUFFIX = {"month": "monthly", "year": "yearly"}
_INTERVAL_ALIASES = {"month": "month", "monthly": "month", "year": "year", "yearly": "year"}
_INTERVAL_LABEL = {"month": "mensal", "year": "anual"}


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict or a Stripe object (which may not subclass ``dict``)."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key, default)


def normalize_interval(interval: str) -> str:
    try:
        return _INTERVAL_ALIASES[interval]
    except KeyError as error:
        raise ValueError(f"unknown billing interval {interval!r}") from error


def lookup_key(plan_key: str, interval: str) -> str:
    return f"{plan_key}_{_LOOKUP_SUFFIX[normalize_interval(interval)]}"


def product_id(plan_key: str) -> str:
    return f"{PRODUCT_ID_PREFIX}{plan_key}"


@dataclass(frozen=True)
class Tier:
    up_to: int | None  # None == "inf"
    flat_amount: int = 0
    unit_amount: int = 0

    def to_params(self) -> dict[str, Any]:
        return {
            "up_to": "inf" if self.up_to is None else self.up_to,
            "flat_amount": self.flat_amount,
            "unit_amount": self.unit_amount,
        }


@dataclass(frozen=True)
class ProductSpec:
    id: str
    plan_key: str
    account_type: str
    name: str
    metadata: dict[str, str] = field(default_factory=dict)

    def create_params(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "metadata": dict(self.metadata)}

    def update_params(self) -> dict[str, Any]:
        return {"name": self.name, "active": True, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class PriceSpec:
    plan_key: str
    interval: str  # "month" | "year"
    lookup_key: str
    product_id: str
    nickname: str
    currency: str = CURRENCY
    unit_amount: int | None = None  # flat (per_unit) prices
    tiers: tuple[Tier, ...] | None = None  # graduated tiered prices
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_tiered(self) -> bool:
        return self.tiers is not None

    def create_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "product": self.product_id,
            "currency": self.currency,
            "recurring": {"interval": self.interval, "interval_count": 1, "usage_type": "licensed"},
            "lookup_key": self.lookup_key,
            "nickname": self.nickname,
            "metadata": dict(self.metadata),
        }
        if self.is_tiered:
            params["billing_scheme"] = "tiered"
            params["tiers_mode"] = "graduated"
            params["tiers"] = [tier.to_params() for tier in self.tiers or ()]
        else:
            params["billing_scheme"] = "per_unit"
            params["unit_amount"] = self.unit_amount
        return params

    def total_cents(self, quantity: int) -> int:
        """What Stripe charges per interval for ``quantity`` units (graduated tiers or flat per-unit)."""
        if quantity < 0:
            raise ValueError("quantity must be >= 0")
        if not self.is_tiered:
            return (self.unit_amount or 0) * quantity
        total, previous_cap = 0, 0
        for tier in self.tiers or ():
            if quantity <= previous_cap:
                break
            cap = quantity if tier.up_to is None else min(quantity, tier.up_to)
            units = cap - previous_cap
            total += tier.flat_amount + tier.unit_amount * units
            if tier.up_to is None:
                break
            previous_cap = tier.up_to
        return total


def _sellable_by_key() -> dict[str, PlanDefinition]:
    return {plan.plan_key: plan for plan in sellable_plans()}


def _plan(plan_key: str) -> PlanDefinition:
    plans = _sellable_by_key()
    if plan_key not in plans:
        raise KeyError(f"plan {plan_key!r} is not sellable")
    return plans[plan_key]


def desired_products() -> list[ProductSpec]:
    return [
        ProductSpec(
            id=product_id(plan.plan_key),
            plan_key=plan.plan_key,
            account_type=plan.account_type,
            name=f"Arquivio {plan.title}",
            metadata={"plan_key": plan.plan_key, "account_type": plan.account_type, "managed_by": MANAGED_BY},
        )
        for plan in sellable_plans()
    ]


def desired_price(plan_key: str, interval: str) -> PriceSpec:
    plan = _plan(plan_key)
    interval = normalize_interval(interval)
    base = plan.price_year_cents if interval == "year" else plan.price_month_cents
    if base is None:
        raise ValueError(f"plan {plan_key!r} has no {interval} price")
    extra = plan.extra_seat_year_cents if interval == "year" else plan.extra_seat_month_cents
    metadata = {
        "plan_key": plan.plan_key,
        "interval": interval,
        "account_type": plan.account_type,
        "managed_by": MANAGED_BY,
    }
    common = {
        "plan_key": plan.plan_key,
        "interval": interval,
        "lookup_key": lookup_key(plan.plan_key, interval),
        "product_id": product_id(plan.plan_key),
        "nickname": f"{plan.title} ({_INTERVAL_LABEL[interval]})",
        "metadata": metadata,
    }
    if extra is None:  # flat price, quantity 1
        return PriceSpec(unit_amount=base, **common)
    tiers = (
        Tier(up_to=plan.included_seats, flat_amount=base, unit_amount=0),
        Tier(up_to=None, flat_amount=0, unit_amount=extra),
    )
    metadata["included_seats"] = str(plan.included_seats)
    return PriceSpec(tiers=tiers, **common)


def max_charge_cents(plan_key: str, interval: str) -> int:
    """Largest amount one billing cycle of ``plan_key`` can cost (at ``max_seats``; ``included_seats`` if unlimited).

    Used as the Pix Automático mandate ceiling so seat changes within the plan never exceed the mandate.
    """
    plan = _plan(plan_key)
    seats = plan.max_seats if plan.max_seats is not None else plan.included_seats
    return desired_price(plan_key, interval).total_cents(max(1, seats))


def desired_prices() -> list[PriceSpec]:
    return [desired_price(plan.plan_key, interval) for plan in sellable_plans() for interval in INTERVALS]


def desired_portal_configuration() -> dict[str, Any]:
    """Customer Portal v1: invoices, payment method, tax ID, cancel at period end. Plan/seat changes stay in-app."""
    return {
        "business_profile": {"headline": "Arquivio: assinatura, faturas e forma de pagamento"},
        "features": {
            "customer_update": {"enabled": True, "allowed_updates": ["address", "email", "name", "tax_id"]},
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
            "subscription_update": {"enabled": False},
        },
        "metadata": {"managed_by": MANAGED_BY},
    }


def _normalize_tiers(raw: Any) -> tuple[Tier, ...] | None:
    if raw is None:
        return None
    tiers = []
    for item in raw:
        up_to = get_field(item, "up_to")
        tiers.append(
            Tier(
                up_to=None if up_to in (None, "inf") else int(up_to),
                flat_amount=int(get_field(item, "flat_amount") or 0),
                unit_amount=int(get_field(item, "unit_amount") or 0),
            )
        )
    return tuple(tiers)


def _id_of(value: Any) -> str | None:
    return value if isinstance(value, str) or value is None else get_field(value, "id")


def price_amounts_match(spec: PriceSpec, price: Any) -> bool:
    """True when an existing Stripe Price charges exactly what ``spec`` describes (amounts are immutable)."""
    recurring = get_field(price, "recurring") or {}
    if (get_field(price, "currency") or "").lower() != spec.currency:
        return False
    if _id_of(get_field(price, "product")) != spec.product_id:
        return False
    if get_field(recurring, "interval") != spec.interval or int(get_field(recurring, "interval_count") or 1) != 1:
        return False
    if (get_field(recurring, "usage_type") or "licensed") != "licensed":
        return False
    if spec.is_tiered:
        return (
            get_field(price, "billing_scheme") == "tiered"
            and get_field(price, "tiers_mode") == "graduated"
            and _normalize_tiers(get_field(price, "tiers")) == spec.tiers
        )
    return (get_field(price, "billing_scheme") or "per_unit") == "per_unit" and get_field(
        price, "unit_amount"
    ) == spec.unit_amount


def plan_from_price(price: Any) -> tuple[str | None, str | None]:
    """``(plan_key, interval)`` from ``price.metadata`` falling back to the (expanded) product's metadata.

    Unknown or non-sellable plan keys yield ``(None, None)``. The lookup key is deliberately ignored.
    """
    if price is None:
        return None, None
    metadata = get_field(price, "metadata") or {}
    plan_key = get_field(metadata, "plan_key")
    interval = get_field(metadata, "interval")
    if not plan_key:
        product = get_field(price, "product")
        if product is not None and not isinstance(product, str):
            product_metadata = get_field(product, "metadata") or {}
            plan_key = get_field(product_metadata, "plan_key")
            interval = interval or get_field(product_metadata, "interval")
    if not plan_key or plan_key not in _sellable_by_key():
        return None, None
    if not interval:
        interval = get_field(get_field(price, "recurring") or {}, "interval")
    try:
        return plan_key, normalize_interval(interval) if interval else None
    except ValueError:
        return plan_key, None

