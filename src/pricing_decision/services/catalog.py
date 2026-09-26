from __future__ import annotations

from copy import deepcopy
from typing import Any

from pricing_decision.core.exceptions import SkuNotFoundError


class CatalogService:
    def __init__(self, catalog: dict[str, Any]):
        self._skus: dict[str, dict[str, Any]] = deepcopy(catalog.get("skus", {}))
        self._category_cost: dict[str, float] = catalog.get("category_avg_cost", {})

    def get(self, sku: str, *, unknown_policy: str = "error") -> dict[str, Any]:
        if sku in self._skus:
            item = deepcopy(self._skus[sku])
            item["sku"] = sku
            if item.get("cost") is None:
                item["cost"] = self.category_cost(item.get("category"))
            return item
        if unknown_policy == "category_fallback":
            return {
                "sku": sku,
                "name": sku,
                "list_price": 50.0,
                "cost": self.category_cost(None),
                "msrp": 59.99,
                "map": 0.0,
                "currency": "USD",
                "discountable": True,
                "category": "default",
                "stock": 100,
                "competitor_price": 50.0,
                "fallback": True,
            }
        raise SkuNotFoundError(sku)

    def list_skus(self) -> list[dict[str, Any]]:
        rows = []
        for sku, raw in self._skus.items():
            item = deepcopy(raw)
            item["sku"] = sku
            if item.get("cost") is None:
                item["cost"] = self.category_cost(item.get("category"))
            rows.append(item)
        return rows

    def category_cost(self, category: str | None) -> float:
        return float(self._category_cost.get(category or "default", self._category_cost.get("default", 20.0)))
