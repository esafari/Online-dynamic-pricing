from __future__ import annotations

from typing import Any

from pricing_decision.config import RuntimeConfig
from pricing_decision.core.metrics import metrics
from pricing_decision.core.models import DecisionContext, GuardrailResult
from pricing_decision.core.tracing import stage_span


PRIORITY_RANK = {"legal": 0, "fairness": 1, "margin": 2, "frequency": 3, "operational": 4}


class GuardrailStage:
    """Stage 2 — static pre-filter + dynamic post-check on the discount ladder."""

    def __init__(self, cfg: RuntimeConfig, *, rules_available: bool = True):
        self.cfg = cfg
        self.rules_available = rules_available
        self._cached_rules = cfg.guardrails

    def run(self, ctx: DecisionContext, discounts: list[float] | None = None) -> DecisionContext:
        with stage_span(ctx, "guardrails"):
            rules = self._rules(ctx)
            catalog = ctx.catalog
            features = ctx.features.x_raw if ctx.features else {}
            consent = bool(ctx.features.consent) if ctx.features else False
            discounts = discounts if discounts is not None else self._segment_discounts(ctx)

            allowed: list[str] = []
            blocked: list[dict[str, str]] = []
            reasons: list[str] = []
            constraints: dict[str, Any] = {
                "min_margin": rules.get("min_margin", 0.15),
                "stock": catalog.get("stock", 0),
                "freq_30d": features.get("discount_uses_30d", 0),
                "bot_score": catalog.get("bot_score", 0.0),
                "consent": consent,
            }

            if not catalog.get("discountable", True):
                allowed = ["disc_0"]
                blocked = [{"arm": "any", "reason": "not_discountable"}]
                reasons = ["not_discountable"]
                metrics.inc("pds_guardrail_blocks_total", {"rule": "sku_eligibility"})
            else:
                for discount in discounts:
                    arm_id = _arm_id(discount)
                    price = round(float(catalog["list_price"]) * (1.0 - discount), 2)
                    reason = self._static_block(price, discount, catalog, rules)
                    if reason is None:
                        reason = self._dynamic_block(price, discount, catalog, features, consent, rules, ctx)
                    if reason:
                        blocked.append({"arm": arm_id, "reason": reason})
                        metrics.inc("pds_guardrail_blocks_total", {"rule": reason})
                    else:
                        allowed.append(arm_id)
                        reasons.append(f"{arm_id}_ok")

            if "disc_0" not in allowed:
                # List price is always a fail-safe unless SKU is unknown.
                allowed.insert(0, "disc_0")

            # Deterministic unique order.
            allowed = list(dict.fromkeys(allowed))
            all_blocked = len([a for a in allowed if a != "disc_0"]) == 0 and any(
                b["reason"] != "not_discountable" for b in blocked
            )
            if not allowed:
                allowed = ["disc_0"]
                all_blocked = True
                ctx.mark_degraded("guardrail_all_blocked")

            ctx.guardrails = GuardrailResult(
                allowed_arms=allowed,
                blocked_arms=blocked,
                constraint_vector=constraints,
                guardrail_version=ctx.versions.guardrail_version,
                reason_codes=reasons or ["list_price_only"],
                all_blocked=all_blocked,
                degraded="degraded_guardrails" in ctx.degraded_reasons,
            )
        return ctx

    def _rules(self, ctx: DecisionContext) -> dict[str, Any]:
        if not self.rules_available:
            ctx.mark_degraded("degraded_guardrails")
            if self._cached_rules:
                return self._cached_rules
            ctx.mark_degraded("guardrail_fail_safe")
            return {"min_margin": 1.0, "map_enabled": True, "frequency_cap_30d": 0, "inventory_safety_threshold": 10**9}
        pinned = self.cfg.guardrails.get("version")
        if pinned and pinned != ctx.versions.guardrail_version:
            metrics.inc("pds_guardrail_version_mismatch_total")
        return self.cfg.guardrails

    def _segment_discounts(self, ctx: DecisionContext) -> list[float]:
        ladders = self.cfg.ladders
        by_seg = ladders.get("segments", {})
        return list(by_seg.get(ctx.segment, ladders.get("default", [0.0])))

    def _static_block(self, price: float, discount: float, catalog: dict[str, Any], rules: dict[str, Any]) -> str | None:
        cost = float(catalog.get("cost") or 0.0)
        min_margin = float(rules.get("min_margin", 0.15))
        floor = cost * (1.0 + min_margin)
        if price + 1e-9 < floor:
            return "margin_floor"
        if price - 1e-9 > float(catalog.get("msrp", price)):
            return "above_msrp"
        if rules.get("map_enabled", True) and price + 1e-9 < float(catalog.get("map") or 0.0):
            return "below_map"
        if discount > 0 and not catalog.get("discountable", True):
            return "not_discountable"
        return None

    def _dynamic_block(
        self,
        price: float,
        discount: float,
        catalog: dict[str, Any],
        features: dict[str, Any],
        consent: bool,
        rules: dict[str, Any],
        ctx: DecisionContext,
    ) -> str | None:
        if discount > 0 and features.get("discount_uses_30d", 0) >= rules.get("frequency_cap_30d", 2):
            return "freq_cap"
        if discount > 0 and catalog.get("stock", 0) < rules.get("inventory_safety_threshold", 10):
            return "low_inventory"
        if catalog.get("bot_score", 0.0) >= rules.get("bot_score_max", 0.8):
            return "bot_score"
        if discount > 0 and not consent:
            return "no_consent"
        competitor = catalog.get("competitor_price")
        band = float(rules.get("competitor_band", 0.10))
        if competitor and competitor > 0 and abs(price - competitor) / competitor > band + 1e-9:
            # Only block discounts that wander too far; list price may sit outside band.
            if discount > 0:
                return "competitor_bound"
        # Fairness: keep VIP from receiving deeper discounts than returning by default.
        gap = float(rules.get("fairness_price_gap", 0.08))
        if ctx.segment == "vip" and discount > gap + 0.05:
            return "fairness_gap"
        return None


def _arm_id(discount: float) -> str:
    return f"disc_{int(round(discount * 100))}"
