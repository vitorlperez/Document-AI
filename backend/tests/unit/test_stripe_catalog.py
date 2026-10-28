"""Stripe catalog mapping + catalog sync planning, with an in-memory fake Stripe client (no network, no SDK)."""

from __future__ import annotations

import copy
import itertools
from dataclasses import replace
from pathlib import Path

import pytest

from app.billing import stripe_catalog
from app.billing.stripe_catalog import (
    INTERVALS,
    MANAGED_BY,
    desired_price,
    desired_prices,
    desired_products,
    lookup_key,
    plan_from_price,
    price_amounts_match,
)
from app.entitlements.catalog import seat_price_cents, sellable_plans
from scripts import stripe_sync_catalog as sync

# ---------------------------------------------------------------- pure catalog mapping


@pytest.mark.parametrize("plan", sellable_plans(), ids=lambda plan: plan.plan_key)
@pytest.mark.parametrize("interval", INTERVALS)
def test_stripe_total_equals_catalog_seat_price_for_every_seat_count(plan, interval):
    spec = desired_price(plan.plan_key, interval)
    assert plan.max_seats is not None
    for seats in range(1, plan.max_seats + 1):
        assert spec.total_cents(seats) == seat_price_cents(plan, seats, interval), (plan.plan_key, interval, seats)


def test_price_shapes_follow_the_plan():
    team = desired_price("business_team", "month")
    assert team.is_tiered and team.unit_amount is None
    params = team.create_params()
    assert params["billing_scheme"] == "tiered" and params["tiers_mode"] == "graduated"
    assert params["tiers"] == [
        {"up_to": 5, "flat_amount": 29_900, "unit_amount": 0},
        {"up_to": "inf", "flat_amount": 0, "unit_amount": 4_900},
    ]
    assert params["currency"] == "brl" and params["recurring"]["interval"] == "month"
    basic = desired_price("personal_basic", "yearly")
    assert not basic.is_tiered and basic.unit_amount == 39_000
    assert basic.create_params()["billing_scheme"] == "per_unit"
    assert basic.metadata == {"plan_key": "personal_basic", "interval": "year", "account_type": "personal",
                              "managed_by": MANAGED_BY}
    assert "payment_method_types" not in params


def test_names_and_ids():
    assert lookup_key("business_team", "month") == "business_team_monthly"
    assert lookup_key("personal_pro", "yearly") == "personal_pro_yearly"
    assert [p.id for p in desired_products()] == [
        "arquivio_personal_basic", "arquivio_personal_pro", "arquivio_business_team", "arquivio_business_scale",
    ]
    assert len({spec.lookup_key for spec in desired_prices()}) == 8
    with pytest.raises(KeyError):
        desired_price("business_trial", "month")
    with pytest.raises(ValueError):
        lookup_key("business_team", "week")


def test_plan_from_price_reads_metadata_then_product_and_ignores_lookup_key():
    assert plan_from_price({"metadata": {"plan_key": "business_scale", "interval": "year"},
                            "lookup_key": "personal_basic_monthly"}) == ("business_scale", "year")
    from_product = {"metadata": {}, "recurring": {"interval": "month"},
                    "product": {"id": "arquivio_personal_pro", "metadata": {"plan_key": "personal_pro"}}}
    assert plan_from_price(from_product) == ("personal_pro", "month")
    assert plan_from_price({"metadata": {}, "product": "prod_x", "lookup_key": "business_team_monthly"}) == (None, None)
    assert plan_from_price({"metadata": {"plan_key": "business_trial"}}) == (None, None)
    assert plan_from_price(None) == (None, None)


def test_catalog_module_does_not_import_stripe():
    source = Path(stripe_catalog.__file__).read_text(encoding="utf-8")
    assert "import stripe" not in source


# ---------------------------------------------------------------- fake Stripe client


class _Service:
    def __init__(self, store: FakeStripe, kind: str):
        self.store, self.kind = store, kind
        self.objects: dict[str, dict] = {}

    def list(self, params=None):
        params = params or {}
        items = list(self.objects.values())
        if "ids" in params:
            items = [o for o in items if o["id"] in params["ids"]]
        if "lookup_keys" in params:
            assert len(params["lookup_keys"]) <= 10
            items = [o for o in items if o.get("lookup_key") in params["lookup_keys"]]
        if "starting_after" in params:
            ids = [o["id"] for o in items]
            items = items[ids.index(params["starting_after"]) + 1:]
        limit = self.store.page_size or params.get("limit", 10)
        return {"object": "list", "data": copy.deepcopy(items[:limit]), "has_more": len(items) > limit}

    def create(self, params, options=None):
        self.store.writes.append(("create", self.kind, params))
        key = (options or {}).get("idempotency_key")
        if key and key in self.store.idempotency:
            return copy.deepcopy(self.store.idempotency[key])
        obj = self.store.build(self.kind, copy.deepcopy(params))
        self.objects[obj["id"]] = obj
        if key:
            self.store.idempotency[key] = copy.deepcopy(obj)
        return copy.deepcopy(obj)

    def update(self, object_id, params):
        self.store.writes.append(("update", self.kind, object_id, params))
        obj = self.objects[object_id]
        for name, value in params.items():
            obj[name] = {**obj.get(name, {}), **value} if name == "metadata" else copy.deepcopy(value)
        return copy.deepcopy(obj)


class _Namespace:
    pass


class FakeStripe:
    def __init__(self, page_size: int | None = None):
        self.writes: list[tuple] = []
        self.idempotency: dict[str, dict] = {}
        self.page_size = page_size
        self._ids = itertools.count(1)
        self.v1 = _Namespace()
        self.v1.products = _Service(self, "product")
        self.v1.prices = _Service(self, "price")
        self.v1.billing_portal = _Namespace()
        self.v1.billing_portal.configurations = _Service(self, "portal")

    def build(self, kind: str, params: dict) -> dict:
        if kind == "product":
            if params["id"] in self.v1.products.objects:
                raise RuntimeError("resource_already_exists")
            return {"object": "product", "active": True, "metadata": {}, **params}
        if kind == "portal":
            return {"id": f"bpc_{next(self._ids)}", "object": "billing_portal.configuration", "active": True,
                    "is_default": False, **params}
        transfer = params.pop("transfer_lookup_key", False)
        holder = next((p for p in self.v1.prices.objects.values() if p.get("lookup_key") == params["lookup_key"]),
                      None)
        if holder is not None:
            if not transfer:
                raise RuntimeError("lookup_key already in use")
            holder["lookup_key"] = None
        tiers = params.get("tiers")
        if tiers is not None:  # Stripe returns null for the open-ended tier
            params["tiers"] = [{**t, "up_to": None if t["up_to"] == "inf" else t["up_to"]} for t in tiers]
        return {"id": f"price_{next(self._ids)}", "object": "price", "active": True, "unit_amount": None,
                "tiers_mode": None, **params}

    def price_by_lookup(self, key: str) -> dict:
        return next(p for p in self.v1.prices.objects.values() if p.get("lookup_key") == key)


def _run(client: FakeStripe) -> list[sync.Action]:
    actions = sync.plan_sync(client)
    sync.apply_actions(client, actions)
    return actions


# ---------------------------------------------------------------- sync behaviour


def test_first_run_creates_everything_and_second_run_writes_nothing():
    client = FakeStripe()
    actions = _run(client)
    kinds = [(a.op, a.resource) for a in actions]
    assert kinds.count(("create", "product")) == 4
    assert kinds.count(("create", "price")) == 8
    assert kinds.count(("create", "portal_configuration")) == 1
    assert len(client.writes) == 13
    for spec in desired_prices():
        price = client.price_by_lookup(spec.lookup_key)
        assert price_amounts_match(spec, price)
        assert plan_from_price(price) == (spec.plan_key, spec.interval)
    portal = next(iter(client.v1.billing_portal.configurations.objects.values()))
    assert portal["features"]["subscription_update"] == {"enabled": False}
    assert portal["features"]["subscription_cancel"]["mode"] == "at_period_end"

    client.writes.clear()
    assert sync.plan_sync(client) == []
    assert client.writes == []


def test_dry_run_planning_performs_no_writes():
    client = FakeStripe()
    assert len(sync.plan_sync(client)) == 13
    assert client.writes == []


def test_pagination_is_followed():
    client = FakeStripe()
    _run(client)
    client.page_size = 1
    client.writes.clear()
    assert sync.plan_sync(client) == []


def test_price_change_creates_new_price_transfers_lookup_key_and_archives_old(monkeypatch):
    client = FakeStripe()
    _run(client)
    old = client.price_by_lookup("business_team_monthly")
    client.writes.clear()

    def bumped():
        return [replace(p, extra_seat_month_cents=5_900) if p.plan_key == "business_team" else p
                for p in sellable_plans()]

    monkeypatch.setattr(stripe_catalog, "sellable_plans", bumped)
    actions = _run(client)

    assert [(a.op, a.resource, a.target) for a in actions] == [
        ("create", "price", "business_team_monthly"),
        ("update", "price", "business_team_monthly"),
    ]
    assert actions[0].params["transfer_lookup_key"] is True
    assert actions[1].object_id == old["id"] and actions[1].params == {"active": False}
    new = client.price_by_lookup("business_team_monthly")
    assert new["id"] != old["id"] and new["tiers"][1]["unit_amount"] == 5_900
    archived = client.v1.prices.objects[old["id"]]
    assert archived["active"] is False and archived["lookup_key"] is None
    assert archived["tiers"][1]["unit_amount"] == 4_900  # never edited
    assert [w[0] for w in client.writes] == ["create", "update"]

    client.writes.clear()
    assert sync.plan_sync(client) == []


def test_metadata_drift_updates_without_new_price():
    client = FakeStripe()
    _run(client)
    price = client.price_by_lookup("personal_pro_yearly")
    price["metadata"] = {}
    client.v1.products.objects["arquivio_personal_pro"]["name"] = "old name"
    client.writes.clear()
    actions = _run(client)
    assert [(a.op, a.resource) for a in actions] == [("update", "product"), ("update", "price")]
    assert client.price_by_lookup("personal_pro_yearly")["id"] == price["id"]
    assert sync.plan_sync(client) == []


def test_existing_default_portal_configuration_is_adopted():
    client = FakeStripe()
    client.v1.billing_portal.configurations.objects["bpc_default"] = {
        "id": "bpc_default", "is_default": True, "active": True, "metadata": {},
        "features": {"subscription_update": {"enabled": True}},
    }
    actions = _run(client)
    portal = [a for a in actions if a.resource == "portal_configuration"]
    assert [(a.op, a.object_id) for a in portal] == [("update", "bpc_default")]
    assert sync.plan_sync(client) == []


def test_main_requires_a_key(monkeypatch, capsys):
    monkeypatch.delenv("STRIPE_CATALOG_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert sync.main([]) == 2
    monkeypatch.setenv("STRIPE_CATALOG_API_KEY", "rk_live_" + "x" * 8)
    assert sync.main(["--apply"]) == 2
    assert "x" * 8 not in capsys.readouterr().err


# ---------------------------------------------------------------- Pix mandate ceiling


@pytest.mark.parametrize("plan", sellable_plans(), ids=lambda plan: plan.plan_key)
@pytest.mark.parametrize("interval", INTERVALS)
def test_max_charge_covers_every_allowed_seat_count(plan, interval) -> None:
    ceiling = stripe_catalog.max_charge_cents(plan.plan_key, interval)
    top = plan.max_seats if plan.max_seats is not None else plan.included_seats
    spec = desired_price(plan.plan_key, interval)
    assert ceiling == spec.total_cents(top) == seat_price_cents(plan, top, interval)
    assert all(spec.total_cents(seats) <= ceiling for seats in range(1, top + 1))


def test_max_charge_rejects_unsellable_plans() -> None:
    with pytest.raises(KeyError):
        stripe_catalog.max_charge_cents("business_trial", "month")
