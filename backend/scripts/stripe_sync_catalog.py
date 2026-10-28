"""Sync the Stripe Product/Price catalog and the Customer Portal configuration from ``app.entitlements.catalog``.

    python -m scripts.stripe_sync_catalog            # dry run (default): prints the planned writes
    python -m scripts.stripe_sync_catalog --apply    # performs them

Key: ``STRIPE_CATALOG_API_KEY`` (a restricted key with Products/Prices/Portal write), falling back to
``STRIPE_API_KEY``. The client is pinned to ``settings.stripe_api_version``.

Idempotent per plan: products use stable IDs (``arquivio_<plan_key>``); prices are found by lookup key. A Price whose
amounts differ from the catalog is never edited: a new Price is created with ``transfer_lookup_key=True`` and the old
one is archived (existing subscriptions keep billing on it until migrated). Re-running with no catalog change performs
zero writes. The planning logic only needs a client-like object exposing ``v1.products``, ``v1.prices`` and
``v1.billing_portal.configurations`` (``list``/``create``/``update``), so it is testable without ``stripe``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from app.billing.stripe_catalog import (
    MANAGED_BY,
    PriceSpec,
    ProductSpec,
    desired_portal_configuration,
    desired_prices,
    desired_products,
    get_field,
    price_amounts_match,
)

DEFAULT_API_VERSION = "2026-09-30.endive"


@dataclass(frozen=True)
class Action:
    op: str  # "create" | "update"
    resource: str  # "product" | "price" | "portal_configuration"
    target: str  # product id / lookup key / "portal"
    reason: str
    params: dict[str, Any] = field(default_factory=dict)
    object_id: str | None = None  # for updates
    idempotency_key: str | None = None  # for creates

    def describe(self) -> str:
        suffix = f" ({self.object_id})" if self.object_id else ""
        return f"{self.op:<6} {self.resource:<20} {self.target}{suffix}: {self.reason}"


def _idempotency_key(*parts: Any) -> str:
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"arquivio-catalog-{digest}"


def _iter_list(service: Any, params: dict[str, Any]):
    """Yield every object of a Stripe list call, following ``has_more`` pagination."""
    params = dict(params)
    while True:
        page = service.list(params=params)
        data = list(get_field(page, "data") or [])
        yield from data
        if not get_field(page, "has_more") or not data:
            return
        params["starting_after"] = get_field(data[-1], "id")


def _subset_matches(desired: Any, actual: Any) -> bool:
    """Every key in ``desired`` is present in ``actual`` with an equal value (lists compared as sets)."""
    if isinstance(desired, dict):
        return all(_subset_matches(value, get_field(actual, key)) for key, value in desired.items())
    if isinstance(desired, list):
        return actual is not None and sorted(map(str, desired)) == sorted(map(str, list(actual)))
    return desired == actual


def plan_products(client: Any, specs: list[ProductSpec]) -> list[Action]:
    existing = {
        get_field(product, "id"): product
        for product in _iter_list(client.v1.products, {"ids": [spec.id for spec in specs], "limit": 100})
    }
    actions: list[Action] = []
    for spec in specs:
        product = existing.get(spec.id)
        if product is None:
            actions.append(Action("create", "product", spec.id, "missing", spec.create_params(),
                                  idempotency_key=_idempotency_key("product", spec.create_params())))
            continue
        wanted = spec.update_params()
        if (
            get_field(product, "name") != wanted["name"]
            or not get_field(product, "active")
            or not _subset_matches(wanted["metadata"], get_field(product, "metadata") or {})
        ):
            actions.append(Action("update", "product", spec.id, "name/active/metadata drift", wanted,
                                  object_id=spec.id))
    return actions


def plan_prices(client: Any, specs: list[PriceSpec]) -> list[Action]:
    existing: dict[str, Any] = {}
    keys = [spec.lookup_key for spec in specs]
    for start in range(0, len(keys), 10):  # Stripe accepts up to 10 lookup_keys per list call
        params = {"lookup_keys": keys[start:start + 10], "expand": ["data.tiers"], "limit": 100}
        for price in _iter_list(client.v1.prices, params):
            existing[get_field(price, "lookup_key")] = price
    actions: list[Action] = []
    for spec in specs:
        price = existing.get(spec.lookup_key)
        if price is None:
            params = spec.create_params()
            actions.append(Action("create", "price", spec.lookup_key, "missing", params,
                                  idempotency_key=_idempotency_key("price", params, None)))
            continue
        price_id = get_field(price, "id")
        if not price_amounts_match(spec, price):
            params = {**spec.create_params(), "transfer_lookup_key": True}
            actions.append(Action("create", "price", spec.lookup_key, f"amounts changed; replaces {price_id}",
                                  params, idempotency_key=_idempotency_key("price", params, price_id)))
            if get_field(price, "active"):
                actions.append(Action("update", "price", spec.lookup_key, "archive replaced price",
                                      {"active": False}, object_id=price_id))
            continue
        update: dict[str, Any] = {}
        if not get_field(price, "active"):
            update["active"] = True
        if not _subset_matches(spec.metadata, get_field(price, "metadata") or {}):
            update["metadata"] = dict(spec.metadata)
        if get_field(price, "nickname") != spec.nickname:
            update["nickname"] = spec.nickname
        if update:
            actions.append(Action("update", "price", spec.lookup_key, "non-amount fields drift", update,
                                  object_id=price_id))
    return actions


def plan_portal(client: Any, desired: dict[str, Any]) -> list[Action]:
    configurations = list(_iter_list(client.v1.billing_portal.configurations, {"limit": 100}))
    managed = [c for c in configurations if get_field(get_field(c, "metadata") or {}, "managed_by") == MANAGED_BY]
    default = [c for c in configurations if get_field(c, "is_default")]
    target = (managed or default or [None])[0]
    if target is None:
        return [Action("create", "portal_configuration", "portal", "missing", desired,
                       idempotency_key=_idempotency_key("portal", desired))]
    if _subset_matches(desired, target) and get_field(target, "active", True):
        return []
    params = {**desired, "active": True}
    reason = "drift" if managed else "adopt default configuration"
    return [Action("update", "portal_configuration", "portal", reason, params, object_id=get_field(target, "id"))]


def plan_sync(client: Any, *, include_portal: bool = True) -> list[Action]:
    actions = plan_products(client, desired_products()) + plan_prices(client, desired_prices())
    if include_portal:
        actions += plan_portal(client, desired_portal_configuration())
    return actions


def apply_actions(client: Any, actions: list[Action]) -> list[Any]:
    services = {
        "product": client.v1.products,
        "price": client.v1.prices,
        "portal_configuration": client.v1.billing_portal.configurations,
    }
    results = []
    for action in actions:
        service = services[action.resource]
        if action.op == "create":
            options = {"idempotency_key": action.idempotency_key} if action.idempotency_key else {}
            results.append(service.create(params=action.params, options=options))
        elif action.op == "update":
            results.append(service.update(action.object_id, params=action.params))
        else:  # pragma: no cover - planner never emits other ops
            raise ValueError(f"unknown op {action.op}")
    return results


def _api_version() -> str:
    try:
        from app.core.config import get_settings

        return getattr(get_settings(), "stripe_api_version", None) or DEFAULT_API_VERSION
    except (ImportError, ValueError):  # Settings needs DATABASE_URL etc.; pydantic errors are ValueError
        return os.environ.get("STRIPE_API_VERSION") or DEFAULT_API_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="print planned writes (default)")
    mode.add_argument("--apply", action="store_true", help="perform the planned writes")
    parser.add_argument("--no-portal", action="store_true", help="skip the Customer Portal configuration")
    parser.add_argument("--confirm-live", action="store_true", help="required to --apply with a live-mode key")
    args = parser.parse_args(argv)

    api_key = os.environ.get("STRIPE_CATALOG_API_KEY") or os.environ.get("STRIPE_API_KEY")
    if not api_key:
        print("set STRIPE_CATALOG_API_KEY (or STRIPE_API_KEY)", file=sys.stderr)
        return 2
    live = "_live_" in api_key
    if args.apply and live and not args.confirm_live:
        print("refusing to --apply with a live-mode key without --confirm-live", file=sys.stderr)
        return 2

    import stripe  # lazy: only the CLI needs the SDK

    api_version = _api_version()
    client = stripe.StripeClient(api_key, stripe_version=api_version)
    print(f"mode={'live' if live else 'test'} api_version={api_version} apply={args.apply}")

    actions = plan_sync(client, include_portal=not args.no_portal)
    if not actions:
        print("catalog in sync: 0 writes")
        return 0
    for action in actions:
        print(action.describe())
    if not args.apply:
        print(f"dry run: {len(actions)} write(s) planned; re-run with --apply")
        return 0
    results = apply_actions(client, actions)
    for action, result in zip(actions, results, strict=True):
        print(f"done   {action.resource:<20} {action.target} -> {get_field(result, 'id')}")
    portal = [r for a, r in zip(actions, results, strict=True) if a.resource == "portal_configuration"]
    if portal and not get_field(portal[0], "is_default"):
        print("note: portal configuration is not the account default; pass its id as `configuration` "
              "when creating portal sessions or make it the default in the Dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
