from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


class ControlPlane:
    """Kill switch, merchandiser freeze, promo calendar, discount budget."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        src = deepcopy(cfg or {})
        self.kill_switch = bool(src.get("kill_switch", False))
        self.merchandiser_freeze = bool(src.get("merchandiser_freeze", False))
        self.daily_discount_budget = float(src.get("daily_discount_budget", 10_000))
        self.exploration_budget_frac = float(src.get("exploration_budget_frac", 0.25))
        self.promo_calendar: list[dict[str, Any]] = list(src.get("promo_calendar") or [])
        self.privacy: dict[str, Any] = dict(src.get("privacy") or {})
        self.fx: dict[str, float] = {k: float(v) for k, v in (src.get("fx") or {"USD": 1.0}).items()}
        self.tax: dict[str, float] = {k: float(v) for k, v in (src.get("tax") or {}).items()}
        self.spent = 0.0
        self.explore_spent = 0.0

    def evaluate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        promo = next((p for p in self.promo_calendar if p.get("active") and p.get("force_list")), None)
        budget_exhausted = self.spent >= self.daily_discount_budget
        explore_cap = self.daily_discount_budget * self.exploration_budget_frac
        explore_exhausted = self.explore_spent >= explore_cap
        force_list = self.kill_switch or self.merchandiser_freeze or bool(promo) or budget_exhausted
        return {
            "kill_switch": self.kill_switch,
            "freeze": self.merchandiser_freeze,
            "promo": promo,
            "budget_exhausted": budget_exhausted,
            "explore_exhausted": explore_exhausted,
            "force_list": force_list,
            "force_exploit": force_list or explore_exhausted,
            "budget_remaining": max(0.0, self.daily_discount_budget - self.spent),
            "channel": (payload or {}).get("channel"),
        }

    def record_spend(self, discount_amount: float, *, explored: bool = False) -> None:
        if discount_amount > 0:
            self.spent += float(discount_amount)
            if explored:
                self.explore_spent += float(discount_amount)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if "kill_switch" in patch:
            self.kill_switch = bool(patch["kill_switch"])
        if "merchandiser_freeze" in patch:
            self.merchandiser_freeze = bool(patch["merchandiser_freeze"])
        if "daily_discount_budget" in patch:
            self.daily_discount_budget = float(patch["daily_discount_budget"])
        if "spent" in patch:
            self.spent = float(patch["spent"])
        if "promo_id" in patch:
            for promo in self.promo_calendar:
                if promo.get("id") == patch["promo_id"]:
                    promo["active"] = bool(patch.get("promo_active", True))
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "kill_switch": self.kill_switch,
            "merchandiser_freeze": self.merchandiser_freeze,
            "daily_discount_budget": self.daily_discount_budget,
            "spent": round(self.spent, 2),
            "budget_remaining": round(max(0.0, self.daily_discount_budget - self.spent), 2),
            "exploration_budget_frac": self.exploration_budget_frac,
            "promo_calendar": self.promo_calendar,
            "privacy": self.privacy,
            **self.evaluate(),
        }

    def tax_rate(self, geo: str) -> float:
        if geo in self.tax:
            return self.tax[geo]
        prefix = geo.split("-")[0] if geo else ""
        return self.tax.get(prefix, 0.0)

    def fx_rate(self, currency: str) -> float:
        return float(self.fx.get(currency, 1.0))


class StickyPriceStore:
    """Same shopper + SKU sees the same price across channels for a TTL."""

    def __init__(self, *, ttl_seconds: int = 1800):
        self.ttl = timedelta(seconds=ttl_seconds)
        self._store: dict[str, dict[str, Any]] = {}

    def _key(self, customer_id: str | None, sku: str) -> str:
        return f"{customer_id or 'guest'}:{sku}"

    def lookup(self, customer_id: str | None, sku: str) -> dict[str, Any] | None:
        rec = self._store.get(self._key(customer_id, sku))
        if not rec:
            return None
        exp = rec.get("expires_at")
        if isinstance(exp, datetime) and exp < datetime.now(timezone.utc):
            self._store.pop(self._key(customer_id, sku), None)
            return None
        return rec

    def remember(
        self,
        *,
        customer_id: str | None,
        sku: str,
        offer: dict[str, Any],
        arm: str,
        decision_id: str,
    ) -> None:
        self._store[self._key(customer_id, sku)] = {
            "offer": offer,
            "arm": arm,
            "decision_id": decision_id,
            "expires_at": datetime.now(timezone.utc) + self.ttl,
        }


def apply_localization(offer_price: float, *, catalog_currency: str, request_currency: str | None, fx: dict[str, float]) -> tuple[float, str, float]:
    """Convert display currency only when the client asked for a different one."""
    target = request_currency or catalog_currency or "USD"
    if target == catalog_currency or not request_currency:
        return offer_price, catalog_currency or "USD", 1.0
    src = float(fx.get(catalog_currency, 1.0))
    dst = float(fx.get(target, 1.0))
    rate = dst / src if src else 1.0
    return round(offer_price * rate, 2), target, rate
